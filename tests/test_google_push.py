"""Independent P0-C checks: synthetic identities, no external requests."""
import time
import json
import unittest
from unittest.mock import patch

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.security.google_push import PushIdentity, require_google_push


class GooglePushTests(unittest.TestCase):
    def setUp(self):
        self.identity = PushIdentity('https://example.test/push', 'push@test.iam.gserviceaccount.com')
        self.claims = dict(aud=self.identity.audience, email=self.identity.service_account_email,
                           iss='https://accounts.google.com', email_verified=True,
                           exp=time.time() + 3600, sub='synthetic-subject')
        self.entered = False
        app = FastAPI()

        @app.post('/push')
        async def handler(principal=Depends(require_google_push(self.identity))):
            self.entered = True
            return {'accepted': True}

        self.client = TestClient(app)

    def request(self, claims=None, headers=None, error=None):
        with patch('app.security.google_push._verify_google_token',
                   return_value=claims or self.claims, side_effect=error) as verifier:
            response = self.client.post('/push', headers=headers if headers is not None else
                                        {'Authorization': 'Bearer synthetic-token'}, content=b'invalid-json')
        return response, verifier

    def test_valid_identity(self):
        response, verifier = self.request()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.entered)
        verifier.assert_called_once_with('synthetic-token', self.identity.audience)

    def test_missing_and_malformed_credentials(self):
        for value in (None, '', 'Basic token', 'Bearer', 'Bearer one two'):
            with self.subTest(value=value):
                response, verifier = self.request(headers={} if value is None else {'Authorization': value})
                self.assertEqual(response.status_code, 401)
                verifier.assert_not_called()
                self.assertFalse(self.entered)

    def test_duplicate_authorization(self):
        response, verifier = self.request(headers=[('Authorization', 'Bearer one'), ('Authorization', 'Bearer two')])
        self.assertEqual(response.status_code, 401)
        verifier.assert_not_called()

    def test_invalid_expired_and_unavailable_verifier(self):
        for error in (ValueError('invalid signature'), ValueError('expired'), RuntimeError('certificate unavailable')):
            response, _ = self.request(error=error)
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json(), {'detail': 'Invalid push identity'})
            self.assertFalse(self.entered)

    def test_rejected_claims(self):
        for key, value in [('aud', 'wrong'), ('aud', [self.identity.audience]),
                           ('iss', 'https://evil.test'), ('email_verified', False),
                           ('email_verified', 'true'), ('email', 'other@test.iam.gserviceaccount.com'),
                           ('sub', ''), ('exp', time.time() - 1), ('exp', '9999999999'),
                           ('exp', float('nan')), ('exp', float('inf'))]:
            with self.subTest(key=key, value=value):
                response, _ = self.request(claims={**self.claims, key: value})
                self.assertEqual(response.status_code, 401)
                self.assertFalse(self.entered)

    def test_missing_claims(self):
        for key in self.claims:
            claims = self.claims.copy()
            del claims[key]
            response, _ = self.request(claims=claims)
            self.assertEqual(response.status_code, 401)

    def test_configuration_required(self):
        for audience, email in [('', self.identity.service_account_email), ('test', ''), ('test', 'user@example.test')]:
            with self.assertRaises(ValueError):
                PushIdentity(audience, email)


class GoogleLibraryTests(unittest.TestCase):
    """Exercise real google-auth crypto with a local key and mocked cert transport."""
    def test_signature_and_standard_claim_validation(self):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from google.auth import crypt, jwt
        from google.auth.exceptions import GoogleAuthError
        from app.security.google_push import _verify_google_token

        private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption())
        public = private.public_key().public_bytes(serialization.Encoding.PEM,
                                                   serialization.PublicFormat.SubjectPublicKeyInfo)
        signer = crypt.RSASigner.from_string(pem, key_id='test-key')
        claims = dict(aud='test-audience', iss='https://accounts.google.com',
                      iat=int(time.time()) - 60, exp=int(time.time()) + 3600)

        class CertResponse:
            status = 200
            data = json.dumps({'test-key': public.decode()}).encode()

        with patch('google.auth.transport.requests.Request.__call__', return_value=CertResponse()) as transport:
            token = jwt.encode(signer, claims).decode()
            self.assertEqual(_verify_google_token(token, 'test-audience')['aud'], 'test-audience')
            self.assertEqual(transport.call_args.kwargs['timeout'], 5)
            for overrides in ({'aud': 'wrong'}, {'iss': 'https://evil.test'},
                              {'exp': int(time.time()) - 10}, {'iat': int(time.time()) + 3600}):
                with self.subTest(overrides=overrides), self.assertRaises((ValueError, GoogleAuthError)):
                    _verify_google_token(jwt.encode(signer, {**claims, **overrides}).decode(), 'test-audience')
            # Sign with an independent key while advertising the original key ID.
            other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            other_pem = other.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption())
            wrong_signer = crypt.RSASigner.from_string(other_pem, key_id='test-key')
            with self.assertRaises(ValueError):
                _verify_google_token(jwt.encode(wrong_signer, claims).decode(), 'test-audience')
