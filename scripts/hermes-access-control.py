#!/usr/bin/env python3
import argparse
import json
import secrets
from pathlib import Path

ACCESS_FILE = Path("/opt/hermes-runtime/access-control/users.json")
TOKEN_DIR = Path("/root")


def load_data():
    if not ACCESS_FILE.exists():
        raise SystemExit(f"Access file not found: {ACCESS_FILE}")

    return json.loads(ACCESS_FILE.read_text())


def save_data(data):
    ACCESS_FILE.write_text(json.dumps(data, indent=2) + "\n")
    ACCESS_FILE.chmod(0o600)


def list_users():
    data = load_data()

    print("Hermes RBAC Users")
    print("-----------------")

    for user in data.get("users", []):
        print(f"{user.get('id')} | {user.get('name')} | {user.get('role')} | {user.get('status')} | {','.join(user.get('permissions', []))}")


def add_user(user_id, name, role, permissions):
    data = load_data()

    for user in data.get("users", []):
        if user.get("id") == user_id:
            raise SystemExit(f"User already exists: {user_id}")

    token = secrets.token_urlsafe(48)

    user = {
        "id": user_id,
        "name": name,
        "role": role,
        "status": "active",
        "token": token,
        "permissions": permissions,
    }

    data.setdefault("users", []).append(user)
    save_data(data)

    token_file = TOKEN_DIR / f"hermes-token-{user_id}.txt"
    token_file.write_text(token + "\n")
    token_file.chmod(0o600)

    print(f"Created user: {user_id}")
    print(f"Token saved at: {token_file}")
    print("Token value was not printed.")


def disable_user(user_id):
    data = load_data()

    for user in data.get("users", []):
        if user.get("id") == user_id:
            user["status"] = "disabled"
            save_data(data)
            print(f"Disabled user: {user_id}")
            return

    raise SystemExit(f"User not found: {user_id}")


def main():
    parser = argparse.ArgumentParser(description="Hermes RBAC access control manager")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list")

    add = sub.add_parser("add")
    add.add_argument("--id", required=True)
    add.add_argument("--name", required=True)
    add.add_argument("--role", required=True)
    add.add_argument("--permissions", required=True, help="Comma-separated permissions. Example: messages:understand,jobs:parse")

    disable = sub.add_parser("disable")
    disable.add_argument("--id", required=True)

    args = parser.parse_args()

    if args.command == "list":
        list_users()

    if args.command == "add":
        permissions = [p.strip() for p in args.permissions.split(",") if p.strip()]
        add_user(args.id, args.name, args.role, permissions)

    if args.command == "disable":
        disable_user(args.id)


if __name__ == "__main__":
    main()
