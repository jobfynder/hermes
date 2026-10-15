"""P0-C disabled-route checks; all Google, intake and model effects are mocked."""
import asyncio
import importlib.util
import io
import json
import os
import time
import unittest
from contextlib import ExitStack, contextmanager, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app import config
from app.main import app
from app.routers import gmail_provider
from tests.test_application_auth import send


class DisabledGmailPushTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(config, 'HERMES_GMAIL_PUSH_ENABLED', False))
        self.effects = [self.stack.enter_context(patch(target, side_effect=AssertionError('Side effect forbidden')))
                        for target in [
                            'app.routers.gmail_provider.parse_pubsub_push_envelope',
                            'app.routers.gmail_provider.fetch_new_gmail_messages',
                            'app.routers.gmail_provider.gmail_provider_status',
                            'app.routers.gmail_provider.normalize_gmail_message',
                            'app.routers.gmail_provider.process_channel_intake',
                            'app.security.google_push._verify_google_token',
                            'app.drafts.service.create_draft_object',
                            'app.runtime.db.cursor',
                            'app.prompt_runtime.service.run_prompt',
                            'urllib.request.urlopen',
                        ]]

    def tearDown(self):
        for effect in self.effects:
            effect.assert_not_called()

    def test_disabled_by_default(self):
        # Exercise the actual config source without importing application services.
        namespace = {'__name__': 'isolated_test_config'}
        with patch.dict(os.environ, {}, clear=True):
            exec(compile(Path(config.__file__).read_text(), config.__file__, 'exec'), namespace)
        self.assertIs(namespace['HERMES_GMAIL_PUSH_ENABLED'], False)

    def test_disabled_payloads_and_arbitrary_authorization(self):
        for body in [b'', b'not-json', b'{"message":{"data":"e30=","messageId":"synthetic"}}']:
            for headers in [{}, {'Authorization': 'Bearer arbitrary'}, {'Authorization': 'Basic arbitrary'}]:
                with self.subTest(body_size=len(body), authorization=bool(headers)):
                    r = send('POST', '/providers/gmail/push', content=body, headers=headers)
                    self.assertEqual(r.status_code, 410)
                    self.assertEqual(r.json(), {'detail': 'Gmail push ingestion is disabled'})

    def test_disabled_never_receives_body_or_looks_up_identity(self):
        async def run():
            messages = []
            async def receive():
                self.fail('Disabled request must never read or spool its body')
            async def output(message):
                messages.append(message)
            scope = {'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1',
                     'method': 'POST', 'scheme': 'http', 'path': '/providers/gmail/push',
                     'raw_path': b'/providers/gmail/push', 'query_string': b'',
                     'headers': [(b'content-length', b'999999999')],
                     'client': ('127.0.0.1', 1), 'server': ('test', 80)}
            with patch.object(gmail_provider, 'PushIdentity', side_effect=AssertionError('Identity accessed')):
                await app(scope, receive, output)
            self.assertEqual(next(x['status'] for x in messages if x['type'] == 'http.response.start'), 410)
        asyncio.run(run())

    def test_enabled_incomplete_configuration_fails_before_body(self):
        valid = dict(HERMES_GMAIL_PUSH_ENABLED=True, HERMES_GMAIL_PUSH_PROJECT_ID='test-project',
                     HERMES_GMAIL_PUSH_SUBSCRIPTION='projects/test-project/subscriptions/test-push',
                     HERMES_GMAIL_PUSH_AUDIENCE='https://example.test/push',
                     HERMES_GMAIL_PUSH_SERVICE_ACCOUNT_EMAIL='push@test-project.iam.gserviceaccount.com')
        for key in list(valid)[1:]:
            with self.subTest(missing=key), patch.multiple(config, **{**valid, key: ''}):
                r = send('POST', '/providers/gmail/push', content=b'not-json')
                self.assertEqual(r.status_code, 503)
                self.assertEqual(r.json(), {'detail': 'Gmail push ingestion is unavailable'})
        with patch.multiple(config, **{**valid, 'HERMES_GMAIL_PUSH_SUBSCRIPTION': 'projects/other/subscriptions/test'}):
            self.assertEqual(send('POST', '/providers/gmail/push', content=b'not-json').status_code, 503)


class EnabledGmailPushIdentityTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.multiple(config, HERMES_GMAIL_PUSH_ENABLED=True,
            HERMES_GMAIL_PUSH_PROJECT_ID='test-project',
            HERMES_GMAIL_PUSH_SUBSCRIPTION='projects/test-project/subscriptions/test-push',
            HERMES_GMAIL_PUSH_AUDIENCE='https://example.test/push',
            HERMES_GMAIL_PUSH_SERVICE_ACCOUNT_EMAIL='push@test-project.iam.gserviceaccount.com'))
        self.fetch = self.stack.enter_context(patch.object(gmail_provider, 'fetch_new_gmail_messages', return_value=[]))
        self.intake = self.stack.enter_context(patch.object(gmail_provider, 'process_channel_intake'))
        self.stack.enter_context(patch('urllib.request.urlopen', side_effect=AssertionError('Egress forbidden')))
        self.claims = dict(aud='https://example.test/push', email='push@test-project.iam.gserviceaccount.com',
                           iss='https://accounts.google.com', email_verified=True,
                           sub='synthetic-subject', exp=time.time() + 3600)

    def test_missing_and_invalid_token_reject_before_processing(self):
        with patch('app.security.google_push._verify_google_token', side_effect=ValueError('invalid')) as verify:
            for headers in [{}, {'Authorization': 'Bearer synthetic-invalid'}]:
                self.assertEqual(send('POST', '/providers/gmail/push', content=b'not-json', headers=headers).status_code, 401)
            self.assertEqual(verify.call_count, 1)
        self.fetch.assert_not_called()
        self.intake.assert_not_called()

    def test_wrong_issuer_audience_and_service_account_reject(self):
        for key, value in [('iss', 'https://evil.test'), ('aud', 'wrong'), ('email', 'other@test.iam.gserviceaccount.com')]:
            with self.subTest(claim=key), patch('app.security.google_push._verify_google_token', return_value={**self.claims, key: value}):
                self.assertEqual(send('POST', '/providers/gmail/push', content=b'not-json', headers={'Authorization': 'Bearer synthetic'}).status_code, 401)
        self.fetch.assert_not_called()
        self.intake.assert_not_called()

    def test_verified_future_identity_reaches_existing_handler(self):
        with patch('app.security.google_push._verify_google_token', return_value=self.claims), patch.object(gmail_provider, 'gmail_provider_status', return_value={'configured': True}):
            r = send('POST', '/providers/gmail/push', json={'message': {'data': 'e30='}}, headers={'Authorization': 'Bearer synthetic'})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['acknowledged'])
        self.fetch.assert_called_once()
        self.intake.assert_not_called()


class GmailPollingSeparationTests(unittest.TestCase):
    def test_reconciliation_runs_independently_with_push_disabled(self):
        spec = importlib.util.spec_from_file_location('test_reconcile', 'scripts/hermes-850-gmail-reconcile.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        @contextmanager
        def fake_cursor():
            cur = Mock()
            cur.fetchall.return_value = []
            yield cur
        normalized = {'channel': 'email', 'source_message_id': 'synthetic-poll', 'text': 'test', 'content_type': 'text'}
        result = SimpleNamespace(intake_status='parsed')
        with patch.object(config, 'HERMES_GMAIL_PUSH_ENABLED', False), patch.object(module, 'gmail_provider_status', return_value={'configured': True}), patch.object(module, 'list_gmail_message_ids', return_value=['synthetic-poll']) as listing, patch.object(module, 'fetch_gmail_messages', return_value=[{'id': 'synthetic-poll'}]) as fetch, patch.object(module, 'normalize_gmail_message', return_value=normalized), patch.object(module, 'process_channel_intake', return_value=result) as intake, patch.object(module, 'cursor', fake_cursor), patch('urllib.request.urlopen', side_effect=AssertionError('Egress forbidden')), redirect_stdout(io.StringIO()) as output:
            module.main()
        self.assertEqual(json.loads(output.getvalue())['failure_count'], 0)
        listing.assert_called_once()
        fetch.assert_called_once_with(['synthetic-poll'])
        intake.assert_called_once()


if __name__ == '__main__':
    unittest.main()
