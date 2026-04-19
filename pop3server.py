#!/usr/bin/env python3
"""
pop3server.py - POP3 Mail Server with TLS
Built with Twisted.

Usage:
    python pop3server.py -s <mail-storage> -p <port> [options]

Options:
    -s, --storage     Mail storage directory (same as smtpserver)
    -p, --port        POP3 listen port (default: 1100; use 110 as root)
    --ssl-cert        PEM certificate (enables POP3S)
    --ssl-key         PEM private-key
    --ssl-port        POP3S port (default: 9950; use 995 as root)
    --credentials     JSON credentials file (default: users.json)
    --domain          Default domain for bare usernames (default: localhost)
    -v, --verbose     Enable Twisted log output

users.json format:
    {
        "alice@example.com": {
            "password": "plaintext",
            "domain":   "example.com"
        },
        "bob@example.com": {
            "password_hash": "<sha256-hex>",
            "domain":        "example.com"
        }
    }

Notes:
  • POP3 downloads and removes messages from the server (per-spec behaviour).
  • The server is compatible with Thunderbird, Outlook, and any RFC-1939 client.
  • For security in production always use POP3S (implicit TLS on port 995).
"""

import os
import sys
import json
import hashlib
import logging
import argparse
from io import BytesIO

from zope.interface import implementer
from twisted.internet import reactor, ssl, defer
from twisted.mail import pop3
from twisted.python import log
from twisted.internet.protocol import ServerFactory
from twisted.cred import portal, checkers, credentials as cred_creds, error as cred_error

sys.path.insert(0, os.path.dirname(__file__))
from mailstorage import MailStorage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [POP3]  %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Mailbox – one instance per authenticated session
# ---------------------------------------------------------------------------

@implementer(pop3.IMailbox)
class UserMailbox:
    """
    RFC-1939 mailbox backed by our MailStorage.
    Deletions are staged in memory and committed on QUIT (sync).
    """

    def __init__(self, storage: MailStorage, user: str, domain: str):
        self.storage = storage
        self.user = user
        self.domain = domain
        # Snapshot of (filename, bytes) at session start
        self._messages: list[tuple[str, bytes]] = storage.list_messages(user, domain)
        self._deleted: set[int] = set()
        logger.info(f"POP3 session opened for {user}@{domain}  "
                    f"({len(self._messages)} messages)")

    # -- IMailbox interface --

    def listMessages(self, index=None):
        if index is not None:
            if index in self._deleted:
                raise ValueError("Message is marked for deletion")
            if index >= len(self._messages):
                raise ValueError(f"No message at index {index}")
            return len(self._messages[index][1])
        return [
            0 if i in self._deleted else len(data)
            for i, (_, data) in enumerate(self._messages)
        ]

    def getMessage(self, index: int):
        if index in self._deleted:
            raise ValueError("Message is marked for deletion")
        if index >= len(self._messages):
            raise ValueError(f"No message at index {index}")
        self.storage.mark_as_read(self.user, self.domain, self._messages[index][0])
        return BytesIO(self._messages[index][1])

    def getUidl(self, index: int) -> bytes:
        if index in self._deleted:
            raise ValueError("Message is marked for deletion")
        filename = self._messages[index][0]
        return hashlib.md5(filename.encode()).hexdigest().encode()

    def deleteMessage(self, index: int):
        if index >= len(self._messages):
            raise ValueError(f"No message at index {index}")
        self._deleted.add(index)
        logger.debug(f"Staged delete: index {index} ({self._messages[index][0]})")

    def undeleteMessages(self):
        logger.debug(f"Undeleted {len(self._deleted)} messages")
        self._deleted.clear()

    def sync(self):
        """Called on QUIT; physically remove staged messages."""
        for idx in sorted(self._deleted, reverse=True):
            filename = self._messages[idx][0]
            self.storage.delete_message(self.user, self.domain, filename)
            logger.info(f"Deleted on sync: {filename}")
        self._deleted.clear()
        return defer.succeed(None)

    def appendMessage(self, message_data):
        """Not used by POP3 clients but required by IMailbox."""
        pass


# ---------------------------------------------------------------------------
# Credentials checker
# ---------------------------------------------------------------------------

@implementer(checkers.ICredentialsChecker)
class JsonFileCredentialsChecker:
    """
    Verifies username + password against a JSON file.
    Supports both plain-text passwords (for dev) and sha256 hashes.
    """

    credentialInterfaces = (cred_creds.IUsernamePassword,)

    def __init__(self, credentials_file: str):
        self._data: dict = {}
        if os.path.exists(credentials_file):
            with open(credentials_file, "r", encoding="utf-8") as f:
                self._data = json.load(f)
            logger.info(f"Loaded credentials from {credentials_file} "
                        f"({len(self._data)} accounts)")
        else:
            logger.warning(f"Credentials file not found: {credentials_file}")

    def requestAvatarId(self, credentials):
        username = self._str(credentials.username)
        password = self._str(credentials.password)

        account = self._data.get(username)
        if account is None:
            logger.warning(f"Login attempt for unknown user: {username}")
            return defer.fail(cred_error.UnauthorizedLogin("Unknown user"))

        # Accept plain password OR sha256 hash
        pw_hash = hashlib.sha256(password.encode()).hexdigest()
        plain_ok  = account.get("password") == password
        hashed_ok = account.get("password_hash") == pw_hash

        if plain_ok or hashed_ok:
            logger.info(f"Authenticated: {username}")
            return defer.succeed(credentials.username)

        logger.warning(f"Bad password for: {username}")
        return defer.fail(cred_error.UnauthorizedLogin("Bad password"))

    @staticmethod
    def _str(value) -> str:
        return value.decode("utf-8") if isinstance(value, bytes) else str(value)


# ---------------------------------------------------------------------------
# Realm  (maps authenticated username → mailbox avatar)
# ---------------------------------------------------------------------------

@implementer(portal.IRealm)
class MailRealm:
    def __init__(self, storage: MailStorage, default_domain: str,
                 credentials_data: dict):
        self.storage = storage
        self.default_domain = default_domain
        self.credentials_data = credentials_data

    def requestAvatar(self, avatar_id, mind, *interfaces):
        if pop3.IMailbox not in interfaces:
            raise NotImplementedError("Only IMailbox is supported")

        username = avatar_id.decode("utf-8") if isinstance(avatar_id, bytes) else str(avatar_id)

        # Resolve domain: prefer explicit record, then split on @, then default
        account = self.credentials_data.get(username, {})
        if "@" in username:
            user, domain = username.split("@", 1)
        else:
            user = username
            domain = account.get("domain", self.default_domain)
        domain = account.get("domain", domain)

        # Auto-create mailbox directory if needed
        if not self.storage.user_exists(user, domain):
            self.storage.create_user(user, domain)

        mailbox = UserMailbox(self.storage, user, domain)
        return pop3.IMailbox, mailbox, mailbox.sync


# ---------------------------------------------------------------------------
# Protocol factory
# ---------------------------------------------------------------------------

class POP3ServerFactory(ServerFactory):
    protocol = pop3.POP3

    def __init__(self, auth_portal: portal.Portal):
        self._portal = auth_portal

    def buildProtocol(self, addr):
        proto = self.protocol()
        proto.factory = self
        proto.portal = self._portal
        return proto


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Twisted POP3 Mail Server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("-s", "--storage",     required=True,
                        help="Mail storage directory")
    parser.add_argument("-p", "--port", type=int, default=1100,
                        help="POP3 listen port (default: 1100)")
    parser.add_argument("--ssl-cert",  help="PEM certificate file (enables POP3S)")
    parser.add_argument("--ssl-key",   help="PEM private-key file")
    parser.add_argument("--ssl-port",  type=int, default=9950,
                        help="POP3S port (default: 9950)")
    parser.add_argument("--credentials", default="users.json",
                        help="JSON user credentials file (default: users.json)")
    parser.add_argument("--domain",  default="localhost",
                        help="Default domain for bare usernames (default: localhost)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    if args.verbose:
        log.startLogging(sys.stdout)

    storage = MailStorage(args.storage)

    # Build credential checker and auth portal
    checker = JsonFileCredentialsChecker(args.credentials)
    realm   = MailRealm(storage, args.domain, checker._data)
    auth_portal = portal.Portal(realm, [checker])

    factory = POP3ServerFactory(auth_portal)

    # Plain POP3
    reactor.listenTCP(args.port, factory)
    logger.info(f"POP3  listening on port {args.port}")

    # POP3S (implicit TLS)
    if args.ssl_cert and args.ssl_key:
        ssl_ctx = ssl.DefaultOpenSSLContextFactory(args.ssl_key, args.ssl_cert)
        reactor.listenSSL(args.ssl_port, factory, ssl_ctx)
        logger.info(f"POP3S listening on port {args.ssl_port}")

    logger.info("Server ready.  Press Ctrl+C to stop.")
    reactor.run()


if __name__ == "__main__":
    main()
