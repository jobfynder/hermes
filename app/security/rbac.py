import json
import os
from pathlib import Path
from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

bearer_scheme = HTTPBearer(auto_error=False)

ACCESS_CONTROL_FILE = os.getenv(
    "HERMES_ACCESS_CONTROL_FILE",
    "/hermes-runtime/access-control/users.json",
)

RBAC_ENFORCEMENT = os.getenv("HERMES_RBAC_ENFORCEMENT", "disabled").lower()


def is_rbac_enabled() -> bool:
    return RBAC_ENFORCEMENT == "enabled"


def load_access_users() -> list[dict[str, Any]]:
    path = Path(ACCESS_CONTROL_FILE)

    if not path.exists():
        return []

    data = json.loads(path.read_text())
    return data.get("users", [])


def sanitize_user(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": user.get("id"),
        "name": user.get("name"),
        "role": user.get("role"),
        "status": user.get("status"),
        "permissions": user.get("permissions", []),
    }


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict[str, Any]:
    if not is_rbac_enabled():
        return {
            "id": "rbac-disabled",
            "name": "RBAC Disabled",
            "role": "system",
            "status": "active",
            "permissions": ["*"],
        }

    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing access token",
        )

    token = credentials.credentials

    for user in load_access_users():
        if user.get("token") == token and user.get("status") == "active":
            return sanitize_user(user)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid access token",
    )


def require_permission(permission: str):
    def dependency(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
        permissions = user.get("permissions", [])

        if "*" in permissions or permission in permissions:
            return user

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing permission: {permission}",
        )

    return dependency


def get_rbac_status() -> dict[str, Any]:
    path = Path(ACCESS_CONTROL_FILE)

    return {
        "enabled": is_rbac_enabled(),
        "access_control_file": str(path),
        "access_control_file_exists": path.exists(),
        "configured_users": len(load_access_users()),
    }
