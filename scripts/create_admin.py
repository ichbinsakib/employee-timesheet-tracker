"""Create a user, or reset a password, from the desktop's command line.

    python scripts/create_admin.py                      (asks for username/password)
    python scripts/create_admin.py --username boss --role manager
    python scripts/create_admin.py --username admin --reset   (forgotten password)

The first administrator can also be created in the browser at http://localhost:8000
(only from the desktop itself).
"""
from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from backend.auth.security import ROLES, end_all_sessions, hash_password, validate_new_password  # noqa: E402
from backend.database import init_db, session_scope  # noqa: E402
from backend.models import User  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--username")
    ap.add_argument("--role", default="admin", choices=ROLES)
    ap.add_argument("--reset", action="store_true", help="Set a new password for an existing user")
    ap.add_argument("--password-file", help="Read the password from a file instead of prompting (for automation)")
    args = ap.parse_args()

    init_db()
    username = args.username or input("Username: ").strip()
    if args.password_file:
        password = Path(args.password_file).read_text(encoding="utf-8").strip()
    else:
        password = getpass.getpass("Password: ")
        if getpass.getpass("Repeat password: ") != password:
            sys.exit("Passwords do not match.")
    if err := validate_new_password(password):
        sys.exit(err)

    with session_scope() as db:
        user = db.scalar(select(User).where(User.username == username))
        if user and not args.reset:
            sys.exit(f"User '{username}' already exists. Use --reset to set a new password.")
        if not user and args.reset:
            sys.exit(f"User '{username}' does not exist.")
        if user:
            user.password_hash = hash_password(password)
            user.active = True
            end_all_sessions(db, user.id)
            print(f"Password reset for '{username}'. Existing sessions were signed out.")
        else:
            db.add(User(username=username, password_hash=hash_password(password), role=args.role))
            print(f"Created {args.role} '{username}'.")


if __name__ == "__main__":
    main()
