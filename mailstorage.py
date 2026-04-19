#!/usr/bin/env python3
"""
mailstorage.py - Shared Mail Storage Module
Handles filesystem-based email persistence used by SMTP and POP3 servers.

Directory layout:
  <base_path>/
    <domain>/
      <user>/
        index.json          ← metadata index
        YYYYMMDD_HHmmss_uid.eml  ← raw RFC-2822 message files
"""

import os
import json
import hashlib
import logging
from datetime import datetime
from email import message_from_bytes

logger = logging.getLogger(__name__)


class MailStorage:
    """Filesystem-based mail storage with JSON index per mailbox."""

    def __init__(self, base_path: str):
        self.base_path = os.path.abspath(base_path)
        os.makedirs(self.base_path, exist_ok=True)
        logger.info(f"MailStorage initialised at {self.base_path}")

    # ------------------------------------------------------------------ paths

    def _mailbox_path(self, user: str, domain: str) -> str:
        path = os.path.join(self.base_path, domain.lower(), user.lower())
        os.makedirs(path, exist_ok=True)
        return path

    def _index_path(self, user: str, domain: str) -> str:
        return os.path.join(self._mailbox_path(user, domain), "index.json")

    # ------------------------------------------------------------------ index

    def _load_index(self, user: str, domain: str) -> list:
        path = self._index_path(user, domain)
        if not os.path.exists(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Corrupt index for {user}@{domain}: {e}. Resetting.")
            return []

    def _save_index(self, user: str, domain: str, index: list):
        with open(self._index_path(user, domain), "w", encoding="utf-8") as f:
            json.dump(index, f, indent=2, ensure_ascii=False)

    # ------------------------------------------------------------------ write

    def save_message(self, user: str, domain: str, message_data: bytes) -> str:
        """
        Persist *message_data* (raw RFC-2822 bytes) and update the index.
        Returns the full path to the saved file.
        """
        mailbox = self._mailbox_path(user, domain)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        uid = hashlib.md5(f"{ts}{user}{domain}".encode()).hexdigest()[:8]
        filename = f"{ts}_{uid}.eml"
        filepath = os.path.join(mailbox, filename)

        with open(filepath, "wb") as f:
            f.write(message_data)

        self._append_index(user, domain, filename, message_data)
        logger.info(f"Message saved → {filepath}")
        return filepath

    def _append_index(self, user, domain, filename, message_data):
        index = self._load_index(user, domain)
        try:
            msg = message_from_bytes(message_data)
            entry = {
                "filename": filename,
                "uid": hashlib.md5(filename.encode()).hexdigest(),
                "from": msg.get("From", "unknown"),
                "to": msg.get("To", "unknown"),
                "subject": msg.get("Subject", "(no subject)"),
                "date": msg.get("Date", datetime.now().isoformat()),
                "size": len(message_data),
                "read": False,
            }
        except Exception as e:
            logger.error(f"Cannot parse saved message headers: {e}")
            entry = {
                "filename": filename,
                "uid": hashlib.md5(filename.encode()).hexdigest(),
                "size": len(message_data),
                "read": False,
            }
        index.append(entry)
        self._save_index(user, domain, index)

    # ------------------------------------------------------------------ read

    def list_messages(self, user: str, domain: str) -> list:
        """Return sorted list of (filename, bytes) for all messages."""
        mailbox = self._mailbox_path(user, domain)
        result = []
        for fn in sorted(f for f in os.listdir(mailbox) if f.endswith(".eml")):
            try:
                with open(os.path.join(mailbox, fn), "rb") as f:
                    result.append((fn, f.read()))
            except Exception as e:
                logger.error(f"Cannot read {fn}: {e}")
        return result

    def get_message(self, user: str, domain: str, filename: str) -> bytes | None:
        path = os.path.join(self._mailbox_path(user, domain), filename)
        if not os.path.exists(path):
            return None
        with open(path, "rb") as f:
            return f.read()

    # ------------------------------------------------------------------ delete

    def delete_message(self, user: str, domain: str, filename: str) -> bool:
        path = os.path.join(self._mailbox_path(user, domain), filename)
        if not os.path.exists(path):
            return False
        os.remove(path)
        index = [e for e in self._load_index(user, domain) if e.get("filename") != filename]
        self._save_index(user, domain, index)
        logger.info(f"Deleted {filename} for {user}@{domain}")
        return True

    # ------------------------------------------------------------------ helpers

    def mark_as_read(self, user: str, domain: str, filename: str):
        index = self._load_index(user, domain)
        for entry in index:
            if entry.get("filename") == filename:
                entry["read"] = True
        self._save_index(user, domain, index)

    def get_unread_count(self, user: str, domain: str) -> int:
        return sum(1 for e in self._load_index(user, domain) if not e.get("read", False))

    def user_exists(self, user: str, domain: str) -> bool:
        return os.path.isdir(os.path.join(self.base_path, domain.lower(), user.lower()))

    def create_user(self, user: str, domain: str):
        self._mailbox_path(user, domain)  # creates dir
        logger.info(f"Mailbox created for {user}@{domain}")

    def list_users(self, domain: str) -> list:
        domain_path = os.path.join(self.base_path, domain.lower())
        if not os.path.isdir(domain_path):
            return []
        return [
            d for d in os.listdir(domain_path)
            if os.path.isdir(os.path.join(domain_path, d)) and not d.startswith(".")
        ]
