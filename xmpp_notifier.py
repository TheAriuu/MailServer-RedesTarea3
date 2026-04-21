#!/usr/bin/env python3
"""
xmpp_notifier.py - XMPP Notification Service
Sends instant-message alerts to an XMPP/Jabber user when new email arrives.

Configuration file format (JSON):
{
    "jid":      "notifier@xmpp-server.com",
    "password": "secret",
    "server":   "xmpp-server.com",      // optional, defaults to JID domain
    "port":     5222,                   // optional, default 5222
    "recipient": "admin@xmpp-server.com",

    // Per-email-user overrides (optional)
    "user_mapping": {
        "alice@mydomain.com": "alice_xmpp@chat.example.org",
        "bob@mydomain.com":   "bob@jabber.org"
    }
}
"""

import json
import logging
from typing import Optional

from twisted.internet import reactor, defer
from twisted.words.protocols.jabber import jid as jid_module, client as jabber_client
from twisted.words.protocols.jabber.xmlstream import STREAM_END_EVENT
from twisted.words.xish import domish

logger = logging.getLogger(__name__)


class XMPPNotifier:
    """
    Maintains a persistent XMPP connection and sends notification
    messages when the SMTP server receives new email.
    """

    def __init__(self, config: dict):
        self._jid = jid_module.JID(config["jid"])
        self._password = config["password"]
        self._server = config.get("server", self._jid.host)
        self._port = int(config.get("port", 5222))
        self._default_recipient: Optional[str] = config.get("recipient")
        self._user_mapping: dict = config.get("user_mapping", {})

        self._xml_stream = None
        self._pending: list[str] = []   # messages queued before auth
        self._connected = False

        self._connect()

    # ------------------------------------------------------------------ setup

    def _connect(self):
        factory = jabber_client.XMPPClientFactory(self._jid, self._password)
        factory.addBootstrap("//event/stream/authd", self._on_authenticated)
        factory.addBootstrap(STREAM_END_EVENT, self._on_disconnected)
        reactor.connectTCP(self._server, self._port, factory)
        logger.info(f"XMPP: connecting to {self._server}:{self._port} as {self._jid}")

    def _on_authenticated(self, xml_stream):
        self._xml_stream = xml_stream
        self._connected = True
        logger.info(f"XMPP: authenticated as {self._jid}")

        # Advertise presence
        presence = domish.Element(("jabber:client", "presence"))
        presence.addElement("status", content="Mail notification service online")
        xml_stream.send(presence)

        # Flush queued messages
        for msg_text in self._pending:
            self._send_raw(msg_text, self._default_recipient)
        self._pending.clear()

    def _on_disconnected(self, _reason=None):
        logger.warning("XMPP: disconnected, will attempt reconnect in 30s")
        self._connected = False
        self._xml_stream = None
        reactor.callLater(30, self._connect)

    # ------------------------------------------------------------------ public

    def notify(self, user: str, domain: str, detail: str = ""):
        """
        Called by the SMTP server after a message is saved.

        Resolves the target XMPP JID from *user_mapping* or falls back
        to *recipient*.  Queues the message if not yet authenticated.
        """
        email_addr = f"{user}@{domain}"
        recipient_jid = self._user_mapping.get(email_addr, self._default_recipient)

        if not recipient_jid:
            logger.warning(f"XMPP: no recipient configured for {email_addr}")
            return

        msg_text = f"📧 New email for {email_addr}"
        if detail:
            msg_text += f"\n{detail}"

        if self._connected and self._xml_stream:
            self._send_raw(msg_text, recipient_jid)
        else:
            logger.info("XMPP: not connected yet, queuing notification")
            self._pending.append(msg_text)

    def _send_raw(self, body: str, to_jid: str):
        msg = domish.Element(("jabber:client", "message"))
        msg["to"] = to_jid
        msg["type"] = "chat"
        msg.addElement("body", content=body)
        self._xml_stream.send(msg)
        logger.info(f"XMPP notification sent → {to_jid}")

    #Factory:
    @classmethod
    def from_file(cls, config_path: str) -> "XMPPNotifier":
        with open(config_path, "r", encoding="utf-8") as f:
            return cls(json.load(f))
