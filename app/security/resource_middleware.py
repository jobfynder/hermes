"""Bound actual ASGI bytes, including chunked bodies, before handler effects."""
import asyncio
import json
import time
from collections import OrderedDict, deque

from fastapi import HTTPException, Request
from starlette.responses import JSONResponse

from app import config
from app.security import resource_policy as policy
from app.security.rbac import bearer_scheme, get_current_user, require_permission, require_service_permission

UPLOADS = {'/channels/intake/file', '/understanding/parse-file'}
ADMIN_PREFIXES = ('/taxonomy/', '/taxonomy-candidates/', '/taxonomy-enrichment-requests/')
MODEL_PREFIXES = ('/prompts/', '/resume-builder/', '/assistant/', '/context/', '/broadcast/', '/skill-intelligence/') + ADMIN_PREFIXES
MODEL_PATHS = {'/channels/intake', '/onboarding/profile/draft', '/submissions/tracker-update/extract',
               '/submissions/status/extract', '/understanding/parse-text', '/v1/jobs/parse', '/v1/consultants/parse',
               '/v1/messages/understand', '/v1/messages/actions/extract'}

def expensive(path):
    return path in UPLOADS | MODEL_PATHS or path.startswith(MODEL_PREFIXES)

def body_limit(path, content_type):
    if path in UPLOADS:
        return policy.MAX_MULTIPART_BODY_BYTES
    if path in {'/providers/gmail/push', '/channels/telegram/webhook'}:
        return policy.MAX_SMALL_WEBHOOK_BODY_BYTES
    if 'webhook' in path or path == '/internal/comm/intake':
        return policy.MAX_WEBHOOK_BODY_BYTES
    if expensive(path) or 'parse' in path or path in {'/channels/intake', '/onboarding/profile/draft', '/submissions/tracker-update/extract', '/submissions/status/extract'}:
        return policy.MAX_MODEL_INPUT_BYTES
    return policy.MAX_JSON_BODY_BYTES

class ResourceSafetyMiddleware:
    def __init__(self, app):
        self.app = app
        self.active = 0
        self.rates = OrderedDict()

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope['method'] not in {'POST', 'PUT', 'PATCH', 'DELETE'}:
            return await self.app(scope, receive, send)
        path = scope['path']
        # Preserve P0-C's rejection before body/identity access, even for huge bodies.
        if path == '/providers/gmail/push' and not config.HERMES_GMAIL_PUSH_ENABLED:
            return await self.app(scope, receive, send)
        counted = False
        started = False
        budget_token = policy.MODEL_REQUEST_BUDGET.set({'calls': 0})
        async def tracked_send(message):
            nonlocal started
            if message['type'] == 'http.response.start':
                started = True
            await send(message)
        try:
            request = Request(scope)
            if expensive(path):
                principal = get_current_user(await bearer_scheme(request))
                if path in UPLOADS:
                    authorize = require_service_permission('understanding:parse') if path.startswith('/channels/') else require_permission('understanding:parse')
                    authorize(principal)
                now = time.monotonic()
                bucket = ('upload' if path in UPLOADS else 'admin' if path.startswith(ADMIN_PREFIXES)
                          else 'parse' if path in MODEL_PATHS else 'model')
                rate_limit = (policy.MAX_ADMIN_REQUESTS_PER_MINUTE if bucket == 'admin'
                              else policy.MAX_PARSE_REQUESTS_PER_MINUTE if bucket == 'parse'
                              else policy.MAX_MODEL_REQUESTS_PER_MINUTE if bucket == 'model'
                              else policy.MAX_EXPENSIVE_REQUESTS_PER_MINUTE)
                key = (str(principal.get('id')), bucket)
                timestamps = self.rates.setdefault(key, deque())
                self.rates.move_to_end(key)
                while timestamps and timestamps[0] <= now - 60:
                    timestamps.popleft()
                if len(timestamps) >= rate_limit:
                    policy.reject('RATE_LIMITED', 429, route=path, principal_id=principal.get('id'))
                timestamps.append(now)
                while len(self.rates) > 10_000:
                    self.rates.popitem(last=False)
                if self.active >= policy.MAX_EXPENSIVE_CONCURRENCY:
                    policy.reject('RESOURCE_BUSY', 429, route=path)
                self.active += 1
                counted = True
            cap = body_limit(path, request.headers.get('content-type', ''))
            lengths = request.headers.getlist('content-length')
            if lengths:
                if len(lengths) != 1 or not lengths[0].isdigit():
                    raise HTTPException(400, detail={'code': 'INVALID_REQUEST'})
                if int(lengths[0]) > cap:
                    policy.reject('PAYLOAD_TOO_LARGE', route='/claim/{token}' if path.startswith('/claim/') else path, limit=cap)
            data = bytearray()
            async def read_body():
                while True:
                    message = await receive()
                    if message['type'] == 'http.disconnect':
                        raise HTTPException(400, detail={'code': 'INVALID_REQUEST'})
                    chunk = message.get('body', b'')
                    if len(data) + len(chunk) > cap:
                        policy.reject('PAYLOAD_TOO_LARGE', route='/claim/{token}' if path.startswith('/claim/') else path, limit=cap)
                    data.extend(chunk)
                    if not message.get('more_body', False):
                        break
            try:
                await asyncio.wait_for(read_body(), policy.BODY_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                raise HTTPException(408, detail={'code': 'REQUEST_TIMEOUT'}) from None
            if data and ('json' in request.headers.get('content-type', '') or data[:1] in (b'{', b'[')):
                try:
                    value = json.loads(data)
                except (ValueError, RecursionError):
                    raise HTTPException(422, detail={'code': 'INVALID_REQUEST'}) from None
                policy.guard_structure(value, model=expensive(path) and path not in UPLOADS)
            delivered = False
            async def replay():
                nonlocal delivered
                if delivered:
                    return await receive()
                delivered = True
                return {'type': 'http.request', 'body': bytes(data), 'more_body': False}
            await self.app(scope, replay, tracked_send)
        except HTTPException as exc:
            if started:
                raise
            await JSONResponse({'detail': exc.detail}, status_code=exc.status_code)(scope, receive, send)
        finally:
            policy.MODEL_REQUEST_BUDGET.reset(budget_token)
            if counted:
                self.active -= 1
