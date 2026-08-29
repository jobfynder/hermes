import base64
import json

from app.providers.gmail.service import (
    gmail_provider_status,
    normalize_gmail_message,
    parse_pubsub_push_envelope,
)
from app.providers.microsoft_graph.service import (
    microsoft_graph_provider_status,
    normalize_graph_message,
)
from app.email_parsing.parsers import parse_email_business_records


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_gmail_status_is_contract_until_configured() -> None:
    status = gmail_provider_status()
    require(status['configured'] is False, 'Gmail must report unconfigured with no credentials set')
    require(status['status'] == 'contract', 'Gmail status must be contract until HERMES_GMAIL_* is set')
    require(status['uses_llm'] is False, 'Gmail provider must not claim LLM usage')


def test_gmail_message_normalization() -> None:
    encoded_body = base64.urlsafe_b64encode(
        b'Name: Priya Shah\nTitle: Senior Java Developer\nSkills: Java, Spring, AWS\nExperience: 8'
    ).decode('utf-8').rstrip('=')

    message = {
        'id': 'gmail-msg-1',
        'threadId': 'gmail-thread-1',
        'snippet': 'Name: Priya Shah...',
        'internalDate': '1755600000000',
        'payload': {
            'headers': [
                {'name': 'Subject', 'value': 'Hotlist - Java Developers'},
                {'name': 'From', 'value': 'Recruiter <recruiter@example.com>'},
                {'name': 'To', 'value': 'Hotlists <hotlists@jobfynder.com>'},
            ],
            'mimeType': 'text/plain',
            'body': {'data': encoded_body},
        },
    }

    normalized = normalize_gmail_message(message)

    require(normalized['channel'] == 'email', 'Gmail normalization must produce channel=email')
    require(normalized['source_message_id'] == 'gmail-msg-1', 'Gmail message id must carry through')
    require(normalized['sender']['email'] == 'recruiter@example.com', 'Gmail sender email must be extracted from From header')
    require('Priya Shah' in normalized['text'], 'Gmail body text must be decoded from base64url')
    require(
        normalized['metadata']['intended_document_kind'] == 'hotlist',
        'Gmail To header must route to hotlist via classify_recipient_mailbox',
    )

    parsed = parse_email_business_records(normalized['text'], 'hotlist')
    require(parsed['record_count'] >= 1, 'Normalized Gmail hotlist text must parse into at least one record')


def test_gmail_pubsub_envelope_decoding() -> None:
    inner_payload = json.dumps({'emailAddress': 'hotlists@jobfynder.com', 'historyId': '98765'})
    encoded = base64.urlsafe_b64encode(inner_payload.encode('utf-8')).decode('utf-8').rstrip('=')

    envelope = {
        'message': {
            'data': encoded,
            'messageId': 'pubsub-1',
        },
        'subscription': 'projects/x/subscriptions/y',
    }

    parsed = parse_pubsub_push_envelope(envelope)

    require(parsed['email_address'] == 'hotlists@jobfynder.com', 'Pub/Sub envelope must decode emailAddress')
    require(parsed['history_id'] == '98765', 'Pub/Sub envelope must decode historyId')


def test_graph_status_is_contract_until_configured() -> None:
    status = microsoft_graph_provider_status()
    require(status['configured'] is False, 'Microsoft Graph must report unconfigured with no credentials set')
    require(status['status'] == 'contract', 'Microsoft Graph status must be contract until HERMES_MS_GRAPH_* is set')


def test_graph_message_normalization_plain_text() -> None:
    message = {
        'id': 'graph-msg-1',
        'conversationId': 'graph-conv-1',
        'subject': 'Requirement - Senior .NET Developer',
        'receivedDateTime': '2026-08-20T10:00:00Z',
        'from': {'emailAddress': {'address': 'client@example.com', 'name': 'Client Recruiter'}},
        'toRecipients': [{'emailAddress': {'address': 'jobs@jobfynder.com'}}],
        'body': {
            'contentType': 'text',
            'content': (
                'Job Title: Senior .NET Developer\n'
                'Required Skills: C#, .NET, Azure\n'
                'This is a long-term contract role requiring strong backend experience.'
            ),
        },
    }

    normalized = normalize_graph_message(message)

    require(normalized['channel'] == 'email', 'Graph normalization must produce channel=email')
    require(normalized['sender']['email'] == 'client@example.com', 'Graph sender email must be extracted')
    require(
        normalized['metadata']['intended_document_kind'] == 'job_description',
        'Graph To recipient must route to job_description via classify_recipient_mailbox',
    )
    require('Senior .NET Developer' in normalized['text'], 'Graph body content must carry through')

    parsed = parse_email_business_records(normalized['text'], 'job_description')
    require(parsed['record_count'] >= 1, 'Normalized Graph requirement text must parse into at least one record')


def test_graph_message_normalization_strips_html() -> None:
    message = {
        'id': 'graph-msg-2',
        'subject': 'Hotlist',
        'from': {'emailAddress': {'address': 'bench@example.com'}},
        'toRecipients': [{'emailAddress': {'address': 'hotlists@jobfynder.com'}}],
        'body': {
            'contentType': 'html',
            'content': '<p>Name: Alex Kim</p><p>Title: DevOps Engineer</p>',
        },
    }

    normalized = normalize_graph_message(message)

    require('<p>' not in normalized['text'], 'HTML tags must be stripped from Graph message body')
    require('Alex Kim' in normalized['text'], 'Text content must survive HTML stripping')


def test_graph_message_normalization_preserves_line_structure() -> None:
    # Regression fixture for the HERMES-850 "jobs@ mail isn't parsing
    # right" incident: collapsing every block-level tag to a single space
    # (rather than a newline) turned every real HTML email into one giant
    # run-on line, silently breaking every line-anchored field extractor
    # downstream (job title, required skills, company -- anything
    # matching "^Label:" at the start of a line).
    message = {
        'id': 'graph-msg-3',
        'subject': 'Requirement',
        'from': {'emailAddress': {'address': 'recruiter@example.com'}},
        'toRecipients': [{'emailAddress': {'address': 'jobs@jobfynder.com'}}],
        'body': {
            'contentType': 'html',
            'content': (
                '<div>Job Title: Senior Java Developer</div>'
                '<div>End Client: Acme &amp; Co</div>'
                '<div>Location: Austin, TX</div>'
            ),
        },
    }

    normalized = normalize_graph_message(message)
    lines = [line for line in normalized['text'].splitlines() if line.strip()]

    require(
        any(line.strip() == 'Job Title: Senior Java Developer' for line in lines),
        f'Each <div> must become its own line, got: {normalized["text"]!r}',
    )
    require(
        any(line.strip() == 'End Client: Acme & Co' for line in lines),
        f'HTML entities (&amp;) must be decoded, got: {normalized["text"]!r}',
    )


def run() -> None:
    tests = [
        test_gmail_status_is_contract_until_configured,
        test_gmail_message_normalization,
        test_gmail_pubsub_envelope_decoding,
        test_graph_status_is_contract_until_configured,
        test_graph_message_normalization_plain_text,
        test_graph_message_normalization_strips_html,
        test_graph_message_normalization_preserves_line_structure,
    ]

    for test in tests:
        test()
        print(f'PASS: {test.__name__}')

    print('PASS: HERMES-850 Gmail + Microsoft Graph provider checks')


if __name__ == '__main__':
    run()
