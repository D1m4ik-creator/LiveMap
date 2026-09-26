import argparse
import asyncio
import getpass
import re

from sqlalchemy import select

from livemap.core.engine import close_engine, get_session_factory
from livemap.db.models import AdminUser
from livemap.services.auth import hash_password


async def create_user(username: str, role: str) -> None:
    if re.fullmatch(r"[A-Za-z0-9_.-]{3,100}", username) is None:
        raise SystemExit("Username must contain 3-100 letters, digits, '.', '_' or '-'")
    password = getpass.getpass("Password: ")
    confirmation = getpass.getpass("Repeat password: ")
    if password != confirmation:
        raise SystemExit("Passwords do not match")
    try:
        encoded = hash_password(password)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    async with get_session_factory()() as session:
        existing = (await session.execute(select(AdminUser.id).where(AdminUser.username == username))).scalar_one_or_none()
        if existing is not None:
            raise SystemExit("Username already exists")
        session.add(AdminUser(username=username, password_hash=encoded, role=role))
        await session.commit()
    print(f"Created {role} user {username}")


def main() -> None:
    parser = argparse.ArgumentParser(description="LiveMap administration")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create-user", help="Create the first administrator or another user")
    create.add_argument("username")
    create.add_argument("--role", choices=["admin", "editor"], default="admin")
    args = parser.parse_args()
    async def run() -> None:
        try:
            await create_user(args.username, args.role)
        finally:
            await close_engine()

    asyncio.run(run())


if __name__ == "__main__":
    main()
