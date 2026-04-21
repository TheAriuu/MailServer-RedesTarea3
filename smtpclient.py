#!/usr/bin/env python3
"""
smtpclient.py - Bulk Personalised SMTP Client
Reads recipients from a CSV file and sends a personalised message to each.

Usage:
    python smtpclient.py -h <mail-server> -c <csv-file> -m <message-file> [options]

Options:
    -H, --host      Mail server  host[:port]  (default port: 25)
    -c, --csv       CSV file with recipient list
    -m, --message   Message template file
    -f, --from      Sender address (default: from message file header or noreply@localhost)
    --tls           Use STARTTLS
    --ssl           Use implicit SSL/TLS (SMTPS)
    -u, --username  SMTP authentication username
    -P, --password  SMTP authentication password
    --dry-run       Parse and preview without sending

────────────────────────────────────────────────────────────────────────────
CSV format (first row = header):
    name,email,company,...
    Alice,alice@example.com,Acme,...
    Bob,bob@example.org,Globex,...

Message template file format:
    From: noreply@mydomain.com
    Subject: Hello {{name}}, welcome to {{company}}!
    Attachment: /path/to/file.pdf          ← optional, comma-separated
    ---
    Hi {{name}},

    This is a personalised message for you at {{company}}.

    Best regards,
    The Team

Variable syntax: {{column_name}} — matches CSV header names (case-sensitive).
────────────────────────────────────────────────────────────────────────────
"""

import sys
import os
import re
import csv
import ssl
import smtplib
import logging
import argparse
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [CLIENT] %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Template helpers
# ---------------------------------------------------------------------------

_VAR_RE = re.compile(r"\{\{(\w+)\}\}")


def substitute(template: str, variables: dict) -> str:
    """Replace {{var}} placeholders with values from *variables*."""
    def _replace(match):
        key = match.group(1)
        if key not in variables:
            logger.warning(f"Variable '{{{{{key}}}}}' not found in CSV row")
        return variables.get(key, match.group(0))
    return _VAR_RE.sub(_replace, template)


# ---------------------------------------------------------------------------
# Message file parser
# ---------------------------------------------------------------------------

def parse_message_file(path: str) -> tuple[dict, str]:
    """
    Parse a message template file.

    Returns (headers_dict, body_template) where *headers_dict* may contain:
        from, subject, attachment  (all are templates themselves)

    The file is split at the first '---' separator.  Everything before it is
    treated as header key: value lines.  Everything after is the body.
    """
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    headers: dict[str, str] = {}
    body = content

    if "---" in content:
        header_block, body = content.split("---", 1)
        for line in header_block.strip().splitlines():
            if ":" in line:
                key, val = line.split(":", 1)
                headers[key.strip().lower()] = val.strip()

    return headers, body.strip()


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------

def build_message(sender: str, recipient_email: str,
                  subject: str, body: str,
                  attachments: list[str]) -> MIMEMultipart:
    msg = MIMEMultipart()
    msg["From"] = sender
    msg["To"] = recipient_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    for path in attachments:
        path = path.strip()
        if not path:
            continue
        if not os.path.exists(path):
            logger.warning(f"Attachment not found, skipping: {path}")
            continue
        with open(path, "rb") as fh:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(fh.read())
        encoders.encode_base64(part)
        part.add_header(
            "Content-Disposition",
            f'attachment; filename="{os.path.basename(path)}"',
        )
        msg.attach(part)
        logger.debug(f"Attached: {path}")

    return msg


def send_one(smtp_kwargs: dict, sender: str, recipient: str, msg: MIMEMultipart):
    host = smtp_kwargs["host"]
    port = smtp_kwargs["port"]
    use_ssl = smtp_kwargs.get("use_ssl", False)
    use_tls = smtp_kwargs.get("use_tls", False)
    username = smtp_kwargs.get("username")
    password = smtp_kwargs.get("password")

    try:
        if use_ssl:
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, context=ctx) as server:
                server.set_debuglevel(0)
                if username and password:
                    server.login(username, password)
                server.sendmail(sender, recipient, msg.as_string())
        else:
            with smtplib.SMTP(host, port) as server:
                server.ehlo_or_helo_if_needed()
                if use_tls:
                    ctx = ssl.create_default_context()
                    server.starttls(context=ctx)
                    server.ehlo()
                if username and password:
                    server.login(username, password)
                server.sendmail(sender, recipient, msg.as_string())
        return True
    except smtplib.SMTPException as exc:
        logger.error(f"SMTP error sending to {recipient}: {exc}")
        return False
    except OSError as exc:
        logger.error(f"Connection error sending to {recipient}: {exc}")
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Personalised Bulk SMTP Client",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("-H", "--host",     required=True,
                        help="Mail server host[:port]")
    parser.add_argument("-c", "--csv",      required=True,
                        help="CSV file with recipients")
    parser.add_argument("-m", "--message",  required=True,
                        help="Message template file")
    parser.add_argument("-f", "--from-addr", dest="from_addr",
                        default=None, help="Sender email address")
    parser.add_argument("--tls",  action="store_true", help="Use STARTTLS")
    parser.add_argument("--ssl",  action="store_true", help="Use SMTPS (implicit TLS)")
    parser.add_argument("-u", "--username", help="SMTP auth username")
    parser.add_argument("-P", "--password", help="SMTP auth password")
    parser.add_argument("--port", type=int,  default=None,
                        help="Override port (otherwise derived from --ssl/--tls)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print messages without sending")
    args = parser.parse_args()

    # ── Resolve host and port ────────────────────────────────────────────────
    if ":" in args.host:
        host, port_str = args.host.rsplit(":", 1)
        port = int(port_str)
    else:
        host = args.host
        port = args.port or (465 if args.ssl else 587 if args.tls else 25)

    smtp_kwargs = {
        "host": host,
        "port": port,
        "use_ssl": args.ssl,
        "use_tls": args.tls,
        "username": args.username,
        "password": args.password,
    }

    # ── Load template and recipients ─────────────────────────────────────────
    headers, body_template = parse_message_file(args.message)
    subject_template   = headers.get("subject", "(no subject)")
    sender_template    = headers.get("from", args.from_addr or "noreply@localhost")
    attachment_paths   = [a for a in headers.get("attachment", "").split(",") if a.strip()]

    recipients = []
    with open(args.csv, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            recipients.append(dict(row))

    logger.info(f"Loaded {len(recipients)} recipient(s) from {args.csv}")
    logger.info(f"Mail server: {host}:{port}  SSL={args.ssl}  TLS={args.tls}")

    sent = failed = skipped = 0

    for row in recipients:
        # Find email column (try common names)
        email = (
            row.get("email") or row.get("Email") or
            row.get("EMAIL") or row.get("correo") or ""
        ).strip()

        if not email:
            logger.warning(f"Row has no email address: {row}  — skipping")
            skipped += 1
            continue

        # Substitute variables
        subject = substitute(subject_template, row)
        body    = substitute(body_template,    row)
        sender  = substitute(sender_template,  row)

        msg = build_message(sender, email, subject, body, attachment_paths)

        if args.dry_run:
            print(f"\n{'='*60}")
            print(f"TO:      {email}")
            print(f"FROM:    {sender}")
            print(f"SUBJECT: {subject}")
            print(f"BODY:\n{body[:300]}{'...' if len(body) > 300 else ''}")
            sent += 1
            continue

        if send_one(smtp_kwargs, sender, email, msg):
            logger.info(f"  ✓  Sent to {email}")
            sent += 1
        else:
            failed += 1

    print(f"\n{'─'*40}")
    print(f"Results:  sent={sent}  failed={failed}  skipped={skipped}")


if __name__ == "__main__":
    main()
