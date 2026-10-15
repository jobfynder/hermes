"""P0-B HTTP authentication tests: no lifespan, live credentials, DB or network."""
import asyncio
import inspect
import json
import re
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import httpx
from fastapi.routing import APIRoute
from starlette.responses import JSONResponse
from starlette.routing import Mount

from app.main import app
from app.security import rbac


POLICIES = json.loads(Path(__file__).with_name("security_route_policy.json").read_text())
MODIFIED = {k: v for k, v in POLICIES.items() if v.get("p0b_modified")}


def registered_routes(items=None):
    """Include FastAPI's lazy inclusion contexts as well as direct routes."""
    for route in app.routes if items is None else items:
        if hasattr(route, "effective_candidates"):
            yield from registered_routes(route.effective_candidates())
        elif isinstance(route, APIRoute) or isinstance(getattr(route, "original_route", None), APIRoute):
            yield route
        else:
            yield getattr(route, "starlette_route", None) or route


def routes():
    return {
        method + " " + route.path: route
        for route in registered_routes() if hasattr(route, "dependant")
        for method in route.methods if method not in {"HEAD", "OPTIONS"}
    }


def dependencies(dependant):
    for child in dependant.dependencies:
        yield child.call
        yield from dependencies(child)


def request_args(key):
    method, path = key.split(" ", 1)
    path = re.sub(r"\{[^}]+\}", "test-id", path)
    args = {}
    if path == "/channels/intake/file":
        args = {"files": {"file": ("resume.txt", b"test resume", "text/plain")},
                "data": {"source_message_id": "test-id"}}
    elif method == "POST":
        body = {}
        if path == "/channels/intake":
            body = {"channel": "generic_api", "source_message_id": "test-id", "text": "test"}
        elif path == "/integrations/events/identity":
            body = {"event": {}}
        elif path == "/onboarding/profile/draft":
            body = {"session_id": "test-id", "role": "consultant", "profile_text": "test"}
        elif path == "/onboarding/verification/draft":
            body = {"session_id": "test-id", "role": "consultant", "full_name": "Test Person"}
        elif path in {"/submissions/tracker-update/extract", "/submissions/status/extract"}:
            body = {"message": "test"}
        elif path == "/providers/brightdata/linkedin-profile":
            body = {"public_profile_url": "https://www.linkedin.com/in/test"}
        elif path == "/access/authorize":
            body = {"actor_id": "forged", "role": "admin", "action": "post_hotlist", "channel": "generic_api"}
        args["json"] = body
    if path == "/providers/linkedin/authorize":
        args["params"] = {"state": "test-state"}
    return method, path, args


def principal(role="service", permissions=None, token="service-token"):
    return {"id": "verified-principal", "role": role, "name": "test",
            "status": "active", "token": token, "permissions": permissions or []}


def send(method, path, **kwargs):
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            return await client.request(method, path, **kwargs)
    return asyncio.run(run())


class ApplicationAuthenticationTests(unittest.TestCase):
    def setUp(self):
        from app.security import resource_policy
        rate = patch.object(resource_policy, "MAX_EXPENSIVE_REQUESTS_PER_MINUTE", 100_000)
        rate.start()
        self.addCleanup(rate.stop)
        self.rbac = patch.object(rbac, "RBAC_ENFORCEMENT", "enabled")
        self.rbac.start()
        self.addCleanup(self.rbac.stop)
        self.egress = patch("urllib.request.urlopen", side_effect=AssertionError("External call forbidden"))
        self.egress.start()
        self.addCleanup(self.egress.stop)

    def check_requests(self, credential, expected, role="service", permissions=None):
        for key, policy in list(MODIFIED.items()):
            with self.subTest(route=key, credential=credential, role=role):
                route = routes()[key]
                handler = route.dependant.call
                mock_type = AsyncMock if inspect.iscoroutinefunction(handler) else Mock
                reached = mock_type(return_value=JSONResponse({"reached": True}))
                route.dependant.call = reached
                try:
                    perms = permissions if permissions is not None else [policy["permission"]]
                    identity = principal(role=role, permissions=perms)
                    method, path, args = request_args(key)
                    if credential:
                        args["headers"] = {"Authorization": "Bearer " + credential}
                    with patch.object(rbac, "load_access_users", return_value=[identity]):
                        response = send(method, path, **args)
                    self.assertEqual(response.status_code, expected, response.text)
                    if expected == 200:
                        reached.assert_called_once()
                        self.assertEqual(reached.call_args.kwargs["_principal"]["id"], "verified-principal")
                    else:
                        reached.assert_not_called()
                        self.assertNotIn(policy["permission"], response.text)
                finally:
                    route.dependant.call = handler

    def test_every_modified_route_rejects_missing_bearer_without_handler_effects(self):
        self.check_requests(None, 401)

    def test_every_modified_route_rejects_invalid_bearer_without_handler_effects(self):
        self.check_requests("invalid", 401)

    def test_every_modified_route_rejects_insufficient_permission(self):
        self.check_requests("service-token", 403, permissions=["unrelated:read"])

    def test_every_modified_route_accepts_authorized_principal_and_reaches_handler(self):
        for key, policy in list(MODIFIED.items()):
            with self.subTest(route=key):
                role = "admin" if policy["policy"] == "BEARER_ADMIN" else "service"
                # Limit this helper invocation to one route for its appropriate principal.
                with patch.dict(MODIFIED, {key: policy}, clear=True):
                    self.check_requests("service-token", 200, role=role)

    def test_service_routes_reject_body_or_token_user_role_spoofing(self):
        for key, policy in list(MODIFIED.items()):
            if policy["policy"] != "BEARER_SERVICE":
                continue
            with patch.dict(MODIFIED, {key: policy}, clear=True):
                self.check_requests("service-token", 403, role="consultant")

    def test_admin_routes_reject_service_identity_even_with_permission(self):
        for key, policy in list(MODIFIED.items()):
            if policy["policy"] != "BEARER_ADMIN":
                continue
            with patch.dict(MODIFIED, {key: policy}, clear=True):
                self.check_requests("service-token", 403, role="service")

    def test_upload_rejects_before_body_receive_or_multipart_spooling(self):
        async def run():
            received = Mock(side_effect=AssertionError("Unauthorized upload body read"))
            messages = []
            async def capture(message): messages.append(message)
            scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                     "method": "POST", "scheme": "http", "path": "/channels/intake/file",
                     "raw_path": b"/channels/intake/file", "query_string": b"",
                     "headers": [(b"content-type", b"multipart/form-data; boundary=test")],
                     "client": ("127.0.0.1", 1), "server": ("test", 80)}
            await app(scope, received, capture)
            self.assertEqual(next(m["status"] for m in messages if m["type"] == "http.response.start"), 401)
            received.assert_not_called()
        with patch.object(rbac, "load_access_users", return_value=[]):
            asyncio.run(run())

    def test_existing_authenticated_get_and_public_health(self):
        self.assertEqual(send("GET", "/health").status_code, 200)
        self.assertEqual(send("GET", "/matching/policy").status_code, 401)
        with patch.object(rbac, "load_access_users", return_value=[principal(permissions=["matching:evaluate"])]):
            self.assertEqual(send("GET", "/matching/policy", headers={"Authorization": "Bearer service-token"}).status_code, 200)

    def test_existing_explicit_rbac_disabled_development_mode_is_preserved(self):
        with patch.object(rbac, "RBAC_ENFORCEMENT", "disabled"):
            self.assertEqual(send("GET", "/integrations/health").status_code, 200)
            self.assertEqual(send("GET", "/providers").status_code, 200)

    def test_unauthorized_sensitive_routes_do_not_persist_parse_or_execute_models(self):
        from contextlib import ExitStack
        targets = [
            "app.routers.channels.process_channel_intake", "app.routers.channels.process_file_intake",
            "app.intake.storage.store_attachment", "app.routers.onboarding.create_onboarding_session",
            "app.routers.onboarding.create_profile_draft", "app.routers.onboarding.create_verification_draft",
            "app.routers.submissions.extract_tracker_update", "app.routers.submissions.extract_submission_status",
            "app.prompt_runtime.service.run_prompt", "app.prompt_runtime.service._call_litellm_with_model",
            "app.routers.telegram_provider.register_telegram_webhook",
        ]
        with ExitStack() as stack:
            mocks = [stack.enter_context(patch(target, side_effect=AssertionError("Forbidden side effect"))) for target in targets]
            for key in MODIFIED:
                method, path, args = request_args(key)
                self.assertEqual(send(method, path, **args).status_code, 401, key)
            for mock in mocks: mock.assert_not_called()

    def test_existing_submission_auth_dependencies_remain(self):
        for key in ["POST /submissions/evaluate", "POST /submissions/evaluate/from-handoff"]:
            calls = list(dependencies(routes()[key].dependant))
            self.assertIn(rbac.get_current_user, calls)

    def test_telegram_secret_is_required_even_when_unconfigured(self):
        from app.routers import channels
        for configured, header in [("", None), ("test-secret", None), ("test-secret", "wrong")]:
            with self.subTest(configured=bool(configured), supplied=bool(header)), patch.object(channels, "HERMES_TELEGRAM_WEBHOOK_SECRET", configured), patch.object(channels, "get_or_create_session") as session:
                response = send("POST", "/channels/telegram/webhook", json={},
                                headers={"X-Telegram-Bot-Api-Secret-Token": header} if header else {})
                self.assertEqual(response.status_code, 403)
                session.assert_not_called()

    def test_valid_telegram_secret_reaches_existing_session_logic(self):
        from app.routers import channels
        with patch.object(channels, "HERMES_TELEGRAM_WEBHOOK_SECRET", "test-secret"), patch.object(channels, "get_or_create_session", side_effect=RuntimeError("handler reached")) as session:
            with self.assertRaisesRegex(RuntimeError, "handler reached"):
                send("POST", "/channels/telegram/webhook", json={}, headers={"X-Telegram-Bot-Api-Secret-Token": "test-secret"})
            session.assert_called_once()

    def test_comm_hmac_is_preserved_without_bearer(self):
        from app.security import comm_signature
        from app.routers import comm_intake
        import time
        body = json.dumps({"channel": "email", "source_message_id": "test-id", "text": "test"}).encode()
        timestamp = str(int(time.time()))
        with patch.object(comm_signature, "HERMES_COMM_SHARED_SECRET", "test-hmac"), patch.object(comm_intake, "process_channel_intake", side_effect=RuntimeError("signed handler reached")) as intake:
            response = send("POST", "/internal/comm/intake", content=body)
            self.assertEqual(response.status_code, 403)
            intake.assert_not_called()
            signature = comm_signature.build_comm_signature(timestamp, body)
            with self.assertRaisesRegex(RuntimeError, "signed handler reached"):
                send("POST", "/internal/comm/intake", content=body, headers={"X-Jobfynder-Timestamp": timestamp, "X-Jobfynder-Signature": signature})

    def test_claim_token_read_remains_without_bearer(self):
        from app.routers import claim
        with patch.object(claim, "get_claim_by_token", return_value=None) as lookup:
            self.assertEqual(send("GET", "/claim/test-token").status_code, 404)
            lookup.assert_called_once_with("test-token")

    def test_all_comm_webhooks_keep_signature_verification(self):
        from app.security import comm_signature
        paths = ["/internal/comm/intake", "/providers/email/webhook"] + [
            "/providers/" + provider + "/webhook" for provider in ["whatsapp", "slack", "teams", "google-chat"]
        ]
        with patch.object(comm_signature, "HERMES_COMM_SHARED_SECRET", "test-hmac"):
            for path in paths:
                with self.subTest(path=path):
                    self.assertEqual(send("POST", path, json={}).status_code, 403)
                    self.assertEqual(send("POST", path, json={}, headers={"X-Jobfynder-Timestamp": "0", "X-Jobfynder-Signature": "bad"}).status_code, 403)

    def test_claim_confirmation_and_oauth_callback_keep_their_own_mechanisms(self):
        from app.routers import claim, linkedin_provider
        from app.claim.models import ClaimConfirmResult
        with patch.object(claim, "confirm_claim", return_value=ClaimConfirmResult(status="blocked", errors=["claim_not_found"])) as confirm:
            self.assertEqual(send("POST", "/claim/test-token/confirm", json={"corrections": {}}).status_code, 404)
            confirm.assert_called_once()
        with patch.object(linkedin_provider, "exchange_linkedin_code", return_value={"status": "test-only"}) as exchange:
            self.assertEqual(send("GET", "/providers/linkedin/callback", params={"code": "test-code", "state": "test-state"}).status_code, 200)
            exchange.assert_called_once_with("test-code")

    def test_review_static_files_remain_accessible(self):
        self.assertEqual(send("GET", "/review/").status_code, 200)


class RoutePolicyTests(unittest.TestCase):
    def test_registered_routes_exactly_match_explicit_classification(self):
        inventory = set(routes())
        for route in registered_routes():
            if isinstance(route, Mount): inventory.add("MOUNT " + route.path)
            elif not hasattr(route, "dependant"):
                inventory.update(method + " " + route.path for method in getattr(route, "methods", []) if method != "HEAD")
        self.assertEqual(inventory, set(POLICIES))

    def test_bearer_classifications_have_verified_principal_dependency(self):
        for key, policy in POLICIES.items():
            if not policy["policy"].startswith("BEARER_"): continue
            with self.subTest(route=key):
                calls = list(dependencies(routes()[key].dependant))
                self.assertIn(rbac.get_current_user, calls)
                if policy.get("p0b_modified") and policy["policy"] != "BEARER_USER":
                    self.assertTrue(any(getattr(c, "security_policy", None) == policy["policy"] and getattr(c, "required_permission", None) == policy["permission"] for c in calls))

    def test_webhook_exceptions_have_no_bearer_dependency(self):
        exceptions = {"COMM_HMAC", "TELEGRAM_SECRET", "GMAIL_OIDC", "GMAIL_PUSH_DISABLED", "OAUTH_CALLBACK", "CLAIM_TOKEN"}
        for key, policy in POLICIES.items():
            if policy["policy"] in exceptions:
                self.assertNotIn(rbac.get_current_user, list(dependencies(routes()[key].dependant)), key)
        self.assertEqual(POLICIES["POST /providers/gmail/push"]["status"], "DISABLED_BY_DEFAULT")
        from app.routers.gmail_provider import gmail_push_identity
        self.assertIn(gmail_push_identity, list(dependencies(routes()["POST /providers/gmail/push"].dependant)))


if __name__ == "__main__":
    unittest.main()
