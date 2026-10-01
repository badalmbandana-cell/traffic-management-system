"""
CLI for managing authority accounts directly against the users database -
useful for the FIRST admin account setup, resetting a forgotten password, or
bulk-creating accounts, without needing an already-logged-in admin session.

Examples:
    python -m auth.manage_users list
    python -m auth.manage_users create --username officer_2 --password "a-real-password" --role operator
    python -m auth.manage_users delete --username officer_2
    python -m auth.manage_users reset-password --username admin --password "a-new-real-password"

IMPORTANT: change the seeded demo passwords (admin/operator/viewer, all
"<role>12345") before any real deployment - use reset-password above.
"""
from __future__ import annotations

import argparse
import getpass
import sys

from auth.users_db import create_user, delete_user, get_user, hash_password, init_users_db, list_users, get_connection


def cmd_list(args):
    init_users_db()
    users = list_users()
    if not users:
        print("No users yet.")
        return
    print(f"{'ID':<4} {'Username':<20} {'Role':<10} {'Created'}")
    for u in users:
        print(f"{u['id']:<4} {u['username']:<20} {u['role']:<10} {u['created_at']}")


def _prompt_password_if_missing(args) -> str:
    if args.password:
        return args.password
    pw = getpass.getpass("Password: ")
    confirm = getpass.getpass("Confirm password: ")
    if pw != confirm:
        sys.exit("Passwords did not match.")
    return pw


def cmd_create(args):
    init_users_db()
    password = _prompt_password_if_missing(args)
    try:
        user_id = create_user(args.username, password, args.role)
    except ValueError as exc:
        sys.exit(f"Error: {exc}")
    print(f"Created user '{args.username}' (id={user_id}, role={args.role}).")


def cmd_delete(args):
    init_users_db()
    if delete_user(args.username):
        print(f"Deleted user '{args.username}'.")
    else:
        sys.exit(f"User '{args.username}' not found.")


def cmd_reset_password(args):
    init_users_db()
    if get_user(args.username) is None:
        sys.exit(f"User '{args.username}' not found.")
    password = _prompt_password_if_missing(args)
    if len(password) < 8:
        sys.exit("Password must be at least 8 characters.")
    password_hash, salt = hash_password(password)
    with get_connection() as conn:
        conn.execute("UPDATE users SET password_hash = ?, salt = ? WHERE username = ?",
                     (password_hash, salt, args.username))
    print(f"Password updated for '{args.username}'.")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="list all accounts").set_defaults(func=cmd_list)

    c = sub.add_parser("create", help="create a new account")
    c.add_argument("--username", required=True)
    c.add_argument("--password", default=None, help="omit to be prompted securely")
    c.add_argument("--role", required=True, choices=["admin", "operator", "viewer"])
    c.set_defaults(func=cmd_create)

    d = sub.add_parser("delete", help="delete an account")
    d.add_argument("--username", required=True)
    d.set_defaults(func=cmd_delete)

    r = sub.add_parser("reset-password", help="reset an existing account's password")
    r.add_argument("--username", required=True)
    r.add_argument("--password", default=None, help="omit to be prompted securely")
    r.set_defaults(func=cmd_reset_password)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
