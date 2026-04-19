#!/usr/bin/env python3
"""
smtpserver.py - SMTP/ESMTP Mail Server with TLS
Built with Twisted.

Usage:
    python smtpserver.py -d <domains> -s <mail-storage> -p <port> [options]

Options:
    -d, --domains     Comma-separated list of accepted local domains
    -s, --storage     Path to mail storage directory
    -p, --port        SMTP port (default: 2525; use 25 as root)
    --ssl-cert        PEM certificate file for SMTPS / STARTTLS
    --ssl-key         PEM private-key file
    --ssl-port        Dedicated SMTPS port (default: 4650; use 465 as root)
    --starttls        Advertise and handle STARTTLS on the plain port
    --xmpp-config     Path to xmpp_config.json for new-mail notifications
    -v, --verbose     Enable Twisted log output

Examples:
    # Plain SMTP on port 2525, accepting mail for example.com
    python smtpserver.py -d example.com -s /var/mail -p 2525

    # Multiple domains + TLS
    python smtpserver.py -d example.com,mail.example.net \\
        -s /var/mail -p 2525 \\
        --ssl-cert certs/server.crt --ssl-key certs/server.key \\
        --ssl-port 4650 --starttls

    # With XMPP notifications
    python smtpserver.py -d example.com -s /var/mail -p 2525 \\
        --xmpp-config examples/xmpp_config.json
"""

import os
import sys
import argparse
import logging
import json
from io import BytesIO
from datetime import datetime
from zope.interface import implementer

from twisted.internet import reactor, defer, ssl
from twisted.mail import smtp
from twisted.python import log
from twisted.internet.protocol import ServerFactory

# Local modules
sys.path.insert(0, os.path.dirname(__file__))
from mailstorage import MailStorage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [SMTP] %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Message receiver
# ---------------------------------------------------------------------------

@implementer(smtp.IMessage)
class IncomingMessage:
    """
    Accumulates a single incoming email and persists it to disk.
    One instance is created per accepted recipient address.
    """

    def __init__(self, storage: MailStorage, user: str, domain: str,
                 xmpp_notifier=None):
        self.storage = storage
        self.user = user
        self.domain = domain
        self.xmpp_notifier = xmpp_notifier
        self._lines: list[bytes] = []

    # -- IMessage --

    def lineReceived(self, line: bytes):
        self._lines.append(line)

    def eomReceived(self):
        """End-of-message: persist and (optionally) notify via XMPP."""
        raw = b"\r\n".join(self._lines)
        filepath = self.storage.save_message(self.user, self.domain, raw)
        logger.info(f"Delivered → {self.user}@{self.domain}  ({len(raw)} bytes)")

        if self.xmpp_notifier:
            # Extract subject for the notification body
            from email import message_from_bytes as _mfb
            try:
                subject = _mfb(raw).get("Subject", "(no subject)")
            except Exception:
                subject = ""
            self.xmpp_notifier.notify(self.user, self.domain,
                                       f"Subject: {subject}")
        self._lines = []
        return defer.succeed(None)

    def connectionLost(self):
        self._lines = []


# ---------------------------------------------------------------------------
# Delivery validator
# ---------------------------------------------------------------------------

@implementer(smtp.IMessageDelivery)
class MailDelivery:
    """
    Validates senders, recipients and generates Received headers.
    Acts as the 'glue' between the SMTP protocol and our storage layer.
    """

    def __init__(self, storage: MailStorage, accepted_domains: list[str],
                 xmpp_notifier=None):
        self.storage = storage
        self.accepted_domains = {d.lower() for d in accepted_domains}
        self.xmpp_notifier = xmpp_notifier

    def receivedHeader(self, helo, origin, recipients) -> bytes:
        helo_host = helo[0] if helo[0] else "unknown"
        helo_ip   = helo[1] if len(helo) > 1 else "unknown"
        now = datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S +0000")
        return (
            f"Received: from {helo_host} ({helo_ip}) "
            f"by mailserver (Twisted/SMTP); {now}"
        ).encode()

    def validateFrom(self, helo, origin):
        """Accept all senders.  Extend here for SPF/DKIM checks."""
        logger.debug(f"MAIL FROM: {origin}")
        return origin

    def validateTo(self, user) -> callable:
        """
        Accept the recipient only if their domain is in our accepted list.
        Returns a no-arg factory that creates an IncomingMessage.
        """
        domain = self._decode(user.dest.domain).lower()
        local  = self._decode(user.dest.local)

        if domain not in self.accepted_domains:
            logger.warning(f"Rejected RCPT TO: {local}@{domain} (domain not local)")
            raise smtp.SMTPBadRcpt(user)

        logger.info(f"Accepted RCPT TO: {local}@{domain}")
        return lambda: IncomingMessage(self.storage, local, domain,
                                       self.xmpp_notifier)

    @staticmethod
    def _decode(value) -> str:
        return value.decode("utf-8") if isinstance(value, bytes) else str(value)


# ---------------------------------------------------------------------------
# SMTP Factory
# ---------------------------------------------------------------------------

class SMTPServerFactory(ServerFactory):
    """
    Creates ESMTP protocol instances.
    Optionally configures STARTTLS if an SSL context is provided.
    """

    def __init__(self, storage: MailStorage, accepted_domains: list[str],
                 xmpp_notifier=None, ssl_context_factory=None):
        self.storage = storage
        self.accepted_domains = accepted_domains
        self.xmpp_notifier = xmpp_notifier
        self.ssl_context_factory = ssl_context_factory

    def buildProtocol(self, addr):
        proto = smtp.ESMTP()
        proto.factory = self
        proto.delivery = MailDelivery(
            self.storage, self.accepted_domains, self.xmpp_notifier
        )
        # Attach TLS context so the server advertises STARTTLS
        if self.ssl_context_factory:
            proto.ctx = self.ssl_context_factory.getContext()
        return proto


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Twisted SMTP Mail Server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("-d", "--domains",  required=True,
                        help="Comma-separated accepted local domains")
    parser.add_argument("-s", "--storage",  required=True,
                        help="Mail storage directory")
    parser.add_argument("-p", "--port", type=int, default=2525,
                        help="SMTP listen port (default: 2525)")
    parser.add_argument("--ssl-cert",  help="PEM certificate file (enables TLS)")
    parser.add_argument("--ssl-key",   help="PEM private-key file")
    parser.add_argument("--ssl-port",  type=int, default=4650,
                        help="SMTPS port when --ssl-cert/key provided (default: 4650)")
    parser.add_argument("--starttls",  action="store_true",
                        help="Advertise STARTTLS on the plain port")
    parser.add_argument("--xmpp-config",
                        help="JSON config file for XMPP new-mail notifications")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    if args.verbose:
        log.startLogging(sys.stdout)

    domains = [d.strip() for d in args.domains.split(",") if d.strip()]
    storage = MailStorage(args.storage)

    # Ensure mailbox directories exist for every configured domain
    for domain in domains:
        os.makedirs(os.path.join(args.storage, domain), exist_ok=True)

    # Optional XMPP notifier
    xmpp = None
    if args.xmpp_config and os.path.exists(args.xmpp_config):
        from xmpp_notifier import XMPPNotifier
        xmpp = XMPPNotifier.from_file(args.xmpp_config)
        logger.info(f"XMPP notifier loaded from {args.xmpp_config}")

    # Build SSL context if certs are provided
    ssl_ctx = None
    if args.ssl_cert and args.ssl_key:
        ssl_ctx = ssl.DefaultOpenSSLContextFactory(args.ssl_key, args.ssl_cert)
        logger.info(f"TLS enabled (cert={args.ssl_cert}, key={args.ssl_key})")

    use_starttls = ssl_ctx if args.starttls else None
    factory = SMTPServerFactory(storage, domains, xmpp, use_starttls)

    # Plain SMTP (+ optional STARTTLS)
    reactor.listenTCP(args.port, factory)
    logger.info(f"SMTP listening on port {args.port}  |  domains: {', '.join(domains)}")

    # Dedicated SMTPS (implicit TLS)
    if ssl_ctx:
        reactor.listenSSL(args.ssl_port, factory, ssl_ctx)
        logger.info(f"SMTPS listening on port {args.ssl_port}")

    logger.info("Server ready.  Press Ctrl+C to stop.")
    reactor.run()


if __name__ == "__main__":
    main()
