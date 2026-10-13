"""Authenticate channel uploads before FastAPI reads or spools multipart data."""

from fastapi import Request
from fastapi.routing import APIRoute

from app.security.rbac import bearer_scheme, get_current_user, require_service_permission


class ChannelUploadAuthRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()
        if self.path != "/channels/intake/file":
            return handler

        authorize = require_service_permission("understanding:parse")

        async def authenticated_upload(request: Request):
            credentials = await bearer_scheme(request)
            principal = get_current_user(credentials)
            authorize(principal)
            return await handler(request)

        return authenticated_upload
