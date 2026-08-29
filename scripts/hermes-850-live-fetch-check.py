'''Verifies the Gmail/Graph "fetch the actual message" step added on top of
the HERMES-850 foundation. No real HERMES_GMAIL_*/HERMES_MS_GRAPH_*
credentials exist in this environment, so every HTTP call is mocked by
monkeypatching urllib.request.urlopen -- these checks verify the request
shapes, token/cursor handling, and error-swallowing behavior, NOT that a
real Gmail/Graph account actually responds this way. A live pass against
real credentials is still required before this is trusted end-to-end.
'''
import io
import json
import os
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from urllib.request import Request

import app.providers.gmail.service as gmail_service
import app.providers.microsoft_graph.service as graph_service
from app.runtime.jsonl_store import runtime_path


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class FakeResponse:
    def __init__(self, body: dict):
        self._body = json.dumps(body).encode('utf-8')

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


@contextmanager
def patched_urlopen(responses_by_url_substring: dict):
    calls = []

    def fake_urlopen(request: Request, timeout=None):
        calls.append(request.full_url)
        for substring, body in responses_by_url_substring.items():
            if substring in request.full_url:
                return FakeResponse(body)
        raise AssertionError(f'Unexpected URL requested: {request.full_url}')

    original = gmail_service.urlopen
    gmail_service.urlopen = fake_urlopen
    graph_service.urlopen = fake_urlopen
    try:
        yield calls
    finally:
        gmail_service.urlopen = original
        graph_service.urlopen = original


@contextmanager
def env_vars(**kwargs):
    original = {key: os.environ.get(key) for key in kwargs}
    os.environ.update(kwargs)
    try:
        yield
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _reset_gmail_cursor() -> None:
    path = runtime_path('gmail', 'history_cursor.json')
    if path.exists():
        path.unlink()


def test_gmail_fetch_returns_empty_without_credentials() -> None:
    _reset_gmail_cursor()
    with env_vars(
        HERMES_GMAIL_CLIENT_ID='',
        HERMES_GMAIL_CLIENT_SECRET='',
        HERMES_GMAIL_REFRESH_TOKEN='',
    ):
        result = gmail_service.fetch_new_gmail_messages('12345')
    require(result == [], 'fetch_new_gmail_messages must return [] with no credentials configured')


def test_gmail_fetch_establishes_baseline_on_first_notification() -> None:
    _reset_gmail_cursor()
    with env_vars(
        HERMES_GMAIL_CLIENT_ID='id',
        HERMES_GMAIL_CLIENT_SECRET='secret',
        HERMES_GMAIL_REFRESH_TOKEN='refresh',
    ):
        with patched_urlopen({'oauth2.googleapis.com/token': {'access_token': 'tok'}}) as calls:
            result = gmail_service.fetch_new_gmail_messages('100')

    require(result == [], 'First-ever notification must return [] (no prior cursor to diff against)')
    require(
        gmail_service._load_last_history_id() == '100',
        'First notification historyId must be stored as the baseline cursor',
    )
    require(len(calls) == 0, 'No Gmail API calls should happen when establishing the baseline (no token exchange needed yet)')


def test_gmail_fetch_lists_history_and_fetches_new_messages() -> None:
    _reset_gmail_cursor()
    gmail_service._store_last_history_id('100')

    responses = {
        'oauth2.googleapis.com/token': {'access_token': 'tok'},
        '/history?startHistoryId=100': {
            'history': [
                {'messagesAdded': [{'message': {'id': 'msg-1'}}]},
                {'messagesAdded': [{'message': {'id': 'msg-2'}}]},
            ],
            'historyId': '205',
        },
        '/messages/msg-1': {'id': 'msg-1', 'payload': {'headers': []}},
        '/messages/msg-2': {'id': 'msg-2', 'payload': {'headers': []}},
    }

    with env_vars(
        HERMES_GMAIL_CLIENT_ID='id',
        HERMES_GMAIL_CLIENT_SECRET='secret',
        HERMES_GMAIL_REFRESH_TOKEN='refresh',
    ):
        with patched_urlopen(responses):
            result = gmail_service.fetch_new_gmail_messages('205')

    require(len(result) == 2, f'Expected 2 fetched messages, got {len(result)}')
    require({m['id'] for m in result} == {'msg-1', 'msg-2'}, 'Fetched messages must match the IDs from history.list')
    require(
        gmail_service._load_last_history_id() == '205',
        "Cursor must advance to the API response's historyId, not the notification's",
    )


def test_gmail_fetch_swallows_api_errors() -> None:
    _reset_gmail_cursor()
    gmail_service._store_last_history_id('100')

    def raising_urlopen(request, timeout=None):
        raise ConnectionError('simulated network failure')

    with env_vars(
        HERMES_GMAIL_CLIENT_ID='id',
        HERMES_GMAIL_CLIENT_SECRET='secret',
        HERMES_GMAIL_REFRESH_TOKEN='refresh',
    ):
        original = gmail_service.urlopen
        gmail_service.urlopen = raising_urlopen
        try:
            result = gmail_service.fetch_new_gmail_messages('205')
        finally:
            gmail_service.urlopen = original

    require(result == [], 'A failed token exchange must return [] rather than raising')


def test_graph_fetch_returns_none_without_credentials() -> None:
    with env_vars(
        HERMES_MS_GRAPH_CLIENT_ID='',
        HERMES_MS_GRAPH_CLIENT_SECRET='',
        HERMES_MS_GRAPH_TENANT_ID='',
    ):
        result = graph_service.fetch_graph_message('Users/u1/Messages/m1')
    require(result is None, 'fetch_graph_message must return None with no credentials configured')


def test_graph_fetch_acquires_token_and_fetches_message() -> None:
    responses = {
        'login.microsoftonline.com/tenant-1/oauth2/v2.0/token': {'access_token': 'tok'},
        'graph.microsoft.com/v1.0/Users/u1/Messages/m1': {'id': 'm1', 'subject': 'Requirement'},
    }

    with env_vars(
        HERMES_MS_GRAPH_CLIENT_ID='id',
        HERMES_MS_GRAPH_CLIENT_SECRET='secret',
        HERMES_MS_GRAPH_TENANT_ID='tenant-1',
    ):
        with patched_urlopen(responses) as calls:
            result = graph_service.fetch_graph_message('Users/u1/Messages/m1')

    require(result is not None and result['id'] == 'm1', 'Fetched message must match the mocked Graph response')
    require(
        any('login.microsoftonline.com/tenant-1' in url for url in calls),
        'Token request must target the configured tenant',
    )


def test_graph_fetch_swallows_missing_resource() -> None:
    with env_vars(
        HERMES_MS_GRAPH_CLIENT_ID='id',
        HERMES_MS_GRAPH_CLIENT_SECRET='secret',
        HERMES_MS_GRAPH_TENANT_ID='tenant-1',
    ):
        result = graph_service.fetch_graph_message(None)
    require(result is None, 'A notification with no resource field must return None, not raise')


GRAPH_SUBSCRIPTION_ENV = dict(
    HERMES_MS_GRAPH_CLIENT_ID='id',
    HERMES_MS_GRAPH_CLIENT_SECRET='secret',
    HERMES_MS_GRAPH_TENANT_ID='tenant-1',
    HERMES_MS_GRAPH_MAILBOXES='requirements@jobfynder.com',
    HERMES_MS_GRAPH_CLIENT_STATE='super-secret',
    HERMES_PUBLIC_WEBHOOK_BASE_URL='https://hermes.example.com',
)


def _reset_graph_subscriptions() -> None:
    path = runtime_path('microsoft_graph', 'subscriptions.json')
    if path.exists():
        path.unlink()


def test_graph_sync_blocked_without_notification_url() -> None:
    env = {**GRAPH_SUBSCRIPTION_ENV, 'HERMES_PUBLIC_WEBHOOK_BASE_URL': ''}
    with env_vars(**env):
        result = graph_service.sync_graph_subscriptions()
    require(result['status'] == 'blocked', 'Sync must be blocked without a public webhook base URL')


def test_graph_sync_blocked_without_client_state() -> None:
    env = {**GRAPH_SUBSCRIPTION_ENV, 'HERMES_MS_GRAPH_CLIENT_STATE': ''}
    with env_vars(**env):
        result = graph_service.sync_graph_subscriptions()
    require(result['status'] == 'blocked', 'Sync must be blocked without a clientState secret')


def test_graph_sync_blocked_without_mailboxes() -> None:
    env = {**GRAPH_SUBSCRIPTION_ENV, 'HERMES_MS_GRAPH_MAILBOXES': ''}
    with env_vars(**env):
        result = graph_service.sync_graph_subscriptions()
    require(result['status'] == 'blocked', 'Sync must be blocked with no mailboxes configured')


def test_graph_sync_creates_missing_subscription() -> None:
    _reset_graph_subscriptions()
    responses = {
        'login.microsoftonline.com/tenant-1': {'access_token': 'tok'},
        'graph.microsoft.com/v1.0/subscriptions': {
            'id': 'sub-1',
            'expirationDateTime': '2099-01-01T00:00:00.0000000Z',
        },
    }
    with env_vars(**GRAPH_SUBSCRIPTION_ENV):
        with patched_urlopen(responses):
            result = graph_service.sync_graph_subscriptions()

    require(result['status'] == 'completed', 'Sync must complete when fully configured')
    mailbox_result = result['mailboxes']['requirements@jobfynder.com']
    require(mailbox_result['status'] == 'created', f'Expected a created subscription, got {mailbox_result}')
    require(
        graph_service.list_stored_subscriptions()['requirements@jobfynder.com']['id'] == 'sub-1',
        'The created subscription id must be persisted for future renewal',
    )


def test_graph_sync_creates_subscription_for_named_folder() -> None:
    # Regression fixture for the HERMES-850 "emails received in Outlook
    # but never processed" incident: a mailbox-side rule silently routed
    # real job postings into a "Nvoids" subfolder Hermes had never been
    # told to watch -- the Inbox subscription stayed perfectly healthy
    # the whole time, since it was never asked about that folder at all.
    # "mailbox:FolderName" in HERMES_MS_GRAPH_MAILBOXES is the fix:
    # covered here end-to-end, including the folder-name-to-id lookup a
    # custom (non-well-known) folder needs.
    _reset_graph_subscriptions()
    env = {
        **GRAPH_SUBSCRIPTION_ENV,
        'HERMES_MS_GRAPH_MAILBOXES': 'requirements@jobfynder.com:Nvoids',
    }
    responses = {
        'login.microsoftonline.com/tenant-1': {'access_token': 'tok'},
        'graph.microsoft.com/v1.0/users/requirements@jobfynder.com/mailFolders': {
            'value': [
                {'id': 'inbox-id', 'displayName': 'Inbox'},
                {'id': 'nvoids-folder-id', 'displayName': 'Nvoids'},
            ]
        },
        'graph.microsoft.com/v1.0/subscriptions': {
            'id': 'sub-nvoids',
            'expirationDateTime': '2099-01-01T00:00:00.0000000Z',
        },
    }
    with env_vars(**env):
        with patched_urlopen(responses) as calls:
            result = graph_service.sync_graph_subscriptions()

    key = 'requirements@jobfynder.com:Nvoids'
    require(result['status'] == 'completed', 'Sync must complete when fully configured')
    require(
        result['mailboxes'][key]['status'] == 'created',
        f"Expected a created subscription for the named-folder target, got {result['mailboxes']}",
    )
    require(
        graph_service.list_stored_subscriptions()[key]['id'] == 'sub-nvoids',
        'The named-folder subscription must be stored under its own mailbox:FolderName key, '
        'not overwrite (or be overwritten by) an Inbox subscription for the same mailbox',
    )
    require(
        any('mailFolders' in url for url in calls),
        f'Must look up the folder id by display name before subscribing, calls were: {calls}',
    )


def test_graph_sync_leaves_still_valid_subscription_untouched() -> None:
    _reset_graph_subscriptions()
    graph_service._store_subscriptions({
        'requirements@jobfynder.com': {
            'id': 'sub-1',
            'expirationDateTime': '2099-01-01T00:00:00.0000000Z',
        }
    })

    def fail_if_called(request, timeout=None):
        raise AssertionError('No HTTP call should happen for an already-fresh subscription')

    with env_vars(**GRAPH_SUBSCRIPTION_ENV):
        original = graph_service.urlopen
        graph_service.urlopen = fail_if_called
        try:
            result = graph_service.sync_graph_subscriptions()
        finally:
            graph_service.urlopen = original

    require(
        result['mailboxes']['requirements@jobfynder.com']['status'] == 'still_valid',
        'A subscription expiring far in the future must not be renewed early',
    )


def test_graph_sync_renews_expiring_subscription() -> None:
    _reset_graph_subscriptions()
    graph_service._store_subscriptions({
        'requirements@jobfynder.com': {
            'id': 'sub-1',
            # Expires in 1 hour -- inside the 24h renewal window.
            'expirationDateTime': (
                datetime.now(timezone.utc) + timedelta(hours=1)
            ).strftime('%Y-%m-%dT%H:%M:%S.0000000Z'),
        }
    })

    responses = {
        'login.microsoftonline.com/tenant-1': {'access_token': 'tok'},
        'graph.microsoft.com/v1.0/subscriptions/sub-1': {
            'expirationDateTime': '2099-01-01T00:00:00.0000000Z',
        },
    }
    with env_vars(**GRAPH_SUBSCRIPTION_ENV):
        with patched_urlopen(responses):
            result = graph_service.sync_graph_subscriptions()

    require(
        result['mailboxes']['requirements@jobfynder.com']['status'] == 'renewed',
        f"Expected a renewal, got {result['mailboxes']['requirements@jobfynder.com']}",
    )


def test_graph_client_state_verification() -> None:
    with env_vars(HERMES_MS_GRAPH_CLIENT_STATE='super-secret'):
        require(
            graph_service.verify_notification_client_state({'clientState': 'super-secret'}) is True,
            'A matching clientState must verify',
        )
        require(
            graph_service.verify_notification_client_state({'clientState': 'wrong'}) is False,
            'A mismatched clientState must not verify',
        )
        require(
            graph_service.verify_notification_client_state({}) is False,
            'A missing clientState must not verify',
        )

    with env_vars(HERMES_MS_GRAPH_CLIENT_STATE=''):
        require(
            graph_service.verify_notification_client_state({'clientState': 'anything'}) is False,
            'An unconfigured secret must never verify, even against a plausible-looking value',
        )


def run() -> None:
    tests = [
        test_gmail_fetch_returns_empty_without_credentials,
        test_gmail_fetch_establishes_baseline_on_first_notification,
        test_gmail_fetch_lists_history_and_fetches_new_messages,
        test_gmail_fetch_swallows_api_errors,
        test_graph_fetch_returns_none_without_credentials,
        test_graph_fetch_acquires_token_and_fetches_message,
        test_graph_fetch_swallows_missing_resource,
        test_graph_sync_blocked_without_notification_url,
        test_graph_sync_blocked_without_client_state,
        test_graph_sync_blocked_without_mailboxes,
        test_graph_sync_creates_missing_subscription,
        test_graph_sync_creates_subscription_for_named_folder,
        test_graph_sync_leaves_still_valid_subscription_untouched,
        test_graph_sync_renews_expiring_subscription,
        test_graph_client_state_verification,
    ]

    for test in tests:
        test()
        print(f'PASS: {test.__name__}')

    print('PASS: HERMES-850 live-fetch checks (mocked HTTP, no real credentials)')


if __name__ == '__main__':
    run()
