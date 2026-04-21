#!/usr/bin/env python3
"""
Gestiona cuentas de usuario almacenadas en users.json.
Lo usa el servidor Pop3.
Comandos para utilizarlos:
    python user_manager.py add    -u user@domain.com -p password -s /var/mail
    python user_manager.py delete -u user@domain.com
    python user_manager.py list   [--domain example.com]
    python user_manager.py passwd -u user@domain.com -p newpassword
    python user_manager.py info   -u user@domain.com -s /var/mail
"""

import os
import sys
import json
import argparse
import hashlib
import getpass

DEFAULT_CREDS_FILE = "users.json"

def load_creds(path: str) -> dict:
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_creds(path: str, data: dict):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"Saved: {path}")

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


# Comandos:
def cmd_add(args):
    creds = load_creds(args.credentials)
    username = args.username

    if username in creds:
        print(f"El usuario '{username}' ya existe. Use 'passwd' para cambiar password.")
        sys.exit(1)

    password = args.password or getpass.getpass(f"Password for {username}: ")
    domain = username.split("@")[1] if "@" in username else args.domain or "localhost"

    creds[username] = {
        "password_hash": hash_password(password),
        "domain": domain,
    }
    save_creds(args.credentials, creds)

    # Crear el directorio para el buzón
    if args.storage:
        user_part = username.split("@")[0] if "@" in username else username
        mailbox_path = os.path.join(args.storage, domain, user_part)
        os.makedirs(mailbox_path, exist_ok=True)
        print(f"Buzon creado: {mailbox_path}")

    print(f"Usuario '{username}' añadido exitosamente.")

def cmd_delete(args):
    creds = load_creds(args.credentials)
    if args.username not in creds:
        print(f"Usuario '{args.username}' no encontrado.")
        sys.exit(1)
    del creds[args.username]
    save_creds(args.credentials, creds)
    print(f"Usuario '{args.username}' eliminado.")

def cmd_passwd(args):
    creds = load_creds(args.credentials)
    if args.username not in creds:
        print(f"Usuario '{args.username}' no encontrado.")
        sys.exit(1)
    password = args.password or getpass.getpass(f"New password for {args.username}: ")
    creds[args.username]["password_hash"] = hash_password(password)
    # Remove old plain-text password if present
    creds[args.username].pop("password", None)
    save_creds(args.credentials, creds)
    print(f"Password actualizada para '{args.username}'.")

def cmd_list(args):
    creds = load_creds(args.credentials)
    rows = list(creds.items())
    if args.domain:
        rows = [(u, d) for u, d in rows if d.get("domain") == args.domain]
    if not rows:
        print("No se encontraron usuarios.")
        return
    print(f"{'USERNAME':<35}  {'DOMAIN':<25}  AUTH")
    print("─" * 72)
    for username, data in sorted(rows):
        domain = data.get("domain", "?")
        auth   = "hash" if data.get("password_hash") else "plain"
        print(f"{username:<35}  {domain:<25}  {auth}")

def cmd_info(args):
    import glob
    creds = load_creds(args.credentials)
    if args.username not in creds:
        print(f"User '{args.username}' not found in credentials.")
        sys.exit(1)
    data   = creds[args.username]
    domain = data.get("domain", "?")
    user   = args.username.split("@")[0] if "@" in args.username else args.username
    print(f"User:    {args.username}")
    print(f"Domain:  {domain}")
    print(f"Auth:    {'hashed' if data.get('password_hash') else 'plain-text'}")
    if args.storage:
        mailbox = os.path.join(args.storage, domain, user)
        if os.path.isdir(mailbox):
            messages = glob.glob(os.path.join(mailbox, "*.eml"))
            total_size = sum(os.path.getsize(p) for p in messages)
            print(f"Mailbox: {mailbox}")
            print(f"Messages:{len(messages)}  Total size: {total_size:,} bytes")
            index_path = os.path.join(mailbox, "index.json")
            if os.path.exists(index_path):
                with open(index_path) as f:
                    index = json.load(f)
                unread = sum(1 for e in index if not e.get("read", False))
                print(f"Unread:  {unread}")
        else:
            print(f"Mailbox: {mailbox} (not yet created)")


def main():
    parser = argparse.ArgumentParser(
        description="Mail Account Manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--credentials", default=DEFAULT_CREDS_FILE,
                        help=f"Credentials JSON file (default: {DEFAULT_CREDS_FILE})")
    sub = parser.add_subparsers(dest="command", required=True)
    # add
    p_add = sub.add_parser("add", help="Add a new user")
    p_add.add_argument("-u", "--username", required=True)
    p_add.add_argument("-p", "--password", default=None)
    p_add.add_argument("-s", "--storage", default=None)
    p_add.add_argument("--domain", default=None)
    # delete
    p_del = sub.add_parser("delete", help="Remove a user")
    p_del.add_argument("-u", "--username", required=True)
    # passwd
    p_pw = sub.add_parser("passwd", help="Change user password")
    p_pw.add_argument("-u", "--username", required=True)
    p_pw.add_argument("-p", "--password", default=None)
    # list
    p_ls = sub.add_parser("list", help="List all users")
    p_ls.add_argument("--domain", default=None)
    # info
    p_info = sub.add_parser("info", help="Show user details")
    p_info.add_argument("-u", "--username", required=True)
    p_info.add_argument("-s", "--storage", default=None)
    args = parser.parse_args()

    commands = {
        "add":    cmd_add,
        "delete": cmd_delete,
        "passwd": cmd_passwd,
        "list":   cmd_list,
        "info":   cmd_info,
    }
    commands[args.command](args)

if __name__ == "__main__":
    main()
