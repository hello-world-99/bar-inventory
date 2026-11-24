"""Management commands.

    python -m app.cli create-admin <username>   # prompts for the password
    python -m app.cli bootstrap                 # creates the first admin from env when no users exist
"""

import getpass
import sys

from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.security import hash_password
from app.db import get_sessionmaker
from app.models import Role, User


def create_admin(username: str, password: str) -> None:
    with get_sessionmaker()() as db:
        if db.scalar(select(User).where(func.lower(User.username) == username.lower())):
            sys.exit(f"User '{username}' already exists")
        db.add(
            User(
                username=username,
                full_name="",
                password_hash=hash_password(password),
                role=Role.admin,
                is_active=True,
                token_version=0,
            )
        )
        db.commit()
    print(f"Admin '{username}' created")


def bootstrap() -> None:
    s = get_settings()
    with get_sessionmaker()() as db:
        if db.scalar(select(func.count()).select_from(User)):
            return
    if not (s.initial_admin_username and s.initial_admin_password):
        print(
            "No users yet. Set INITIAL_ADMIN_USERNAME / INITIAL_ADMIN_PASSWORD "
            "or run: python -m app.cli create-admin <name>"
        )
        return
    if len(s.initial_admin_password) < 8:
        sys.exit("INITIAL_ADMIN_PASSWORD must be at least 8 characters")
    create_admin(s.initial_admin_username, s.initial_admin_password)


def main(argv: list[str]) -> None:
    if len(argv) >= 2 and argv[0] == "create-admin":
        pw = getpass.getpass("Password: ")
        if len(pw) < 8 or pw != getpass.getpass("Repeat: "):
            sys.exit("Passwords must match and be at least 8 characters")
        create_admin(argv[1], pw)
    elif argv[:1] == ["bootstrap"]:
        bootstrap()
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
