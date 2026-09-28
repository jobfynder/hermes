import base64

from app.providers.gmail.service import normalize_gmail_message


def _encoded(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode()).decode().rstrip('=')


def _message(payload: dict) -> dict:
    return {
        'id': 'gmail-html-1',
        'payload': {
            'headers': [
                {'name': 'Subject', 'value': 'Senior Java Developer'},
                {'name': 'From', 'value': 'Recruiter <recruiter@example.com>'},
                {'name': 'To', 'value': 'collector@example.com'},
            ],
            **payload,
        },
    }


def test_html_only_body_becomes_structured_plain_text():
    html = """<html><head><style>.hidden { color: red }</style></head><body>
        <div>Job Title: Senior Java Developer</div>
        <p>Required Skills: Java &amp; Spring<br>AWS</p>
        <script>doNotInclude()</script></body></html>"""
    normalized = normalize_gmail_message(
        _message({'mimeType': 'text/html', 'body': {'data': _encoded(html)}}),
        default_document_kind='job_description',
    )

    assert '<div>' not in normalized['text']
    assert 'color: red' not in normalized['text']
    assert 'doNotInclude' not in normalized['text']
    assert 'Job Title: Senior Java Developer' in normalized['text']
    assert 'Required Skills: Java & Spring\nAWS' in normalized['text']


def test_multipart_prefers_plain_alternative_and_ignores_attachment():
    payload = {
        'mimeType': 'multipart/mixed',
        'parts': [
            {
                'mimeType': 'application/octet-stream',
                'filename': 'payload.txt',
                'body': {'data': _encoded('<html>attachment data</html>')},
            },
            {
                'mimeType': 'multipart/alternative',
                'parts': [
                    {'mimeType': 'text/html', 'body': {'data': _encoded('<p>HTML version</p>')}},
                    {'mimeType': 'text/plain', 'body': {'data': _encoded('Plain version')}},
                ],
            },
        ],
    }
    normalized = normalize_gmail_message(_message(payload))

    assert 'Plain version' in normalized['text']
    assert 'HTML version' not in normalized['text']
    assert 'attachment data' not in normalized['text']
