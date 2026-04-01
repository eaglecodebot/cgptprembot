import imaplib
import email
import re
from email.header import decode_header
from email.utils import parseaddr

import os
from dotenv import load_dotenv
load_dotenv()

IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993
IMAP_MAILBOX = "INBOX"
ALLOWED_SENDER = "noreply@tm.openai.com"
IMAP_USER = os.getenv("IMAP_USER")
IMAP_PASS = os.getenv("IMAP_PASS")


def _decode_str(value):
    if not value:
        return ""
    parts = decode_header(value)
    decoded = []
    for raw, charset in parts:
        if isinstance(raw, bytes):
            decoded.append(raw.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(raw)
    return "".join(decoded)


def _strip_html(html):
    clean = re.sub(r"<[^>]+>", "", html)
    clean = re.sub(r"\s+", " ", clean)
    return clean.strip()


def _get_body(msg):
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            disp = str(part.get("Content-Disposition", ""))
            if ct == "text/plain" and "attachment" not in disp:
                charset = part.get_content_charset() or "utf-8"
                return part.get_payload(decode=True).decode(charset, errors="replace").strip()
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                charset = part.get_content_charset() or "utf-8"
                raw = part.get_payload(decode=True).decode(charset, errors="replace")
                return _strip_html(raw)
    else:
        charset = msg.get_content_charset() or "utf-8"
        body = msg.get_payload(decode=True).decode(charset, errors="replace").strip()
        if msg.get_content_type() == "text/html":
            return _strip_html(body)
        return body
    return ""


def fetch_latest_email_for_address(target_email: str, imap_user: str = None, imap_pass: str = None):
    imap_user = imap_user or IMAP_USER
    imap_pass = imap_pass or IMAP_PASS
    """
    Search all emails from ALLOWED_SENDER and find the most recent one
    where any recipient header contains target_email.
    Falls back to full header scan to handle catch-all inboxes reliably.
    """
    target_email = target_email.lower().strip()

    with imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT) as mail:
        mail.login(imap_user, imap_pass)
        mail.select(IMAP_MAILBOX, readonly=True)

        # Search only by FROM — don't use TO filter as catch-all inboxes
        # often store emails with mismatched TO headers
        status, data = mail.search(None, f'FROM "{ALLOWED_SENDER}"')
        if status != "OK" or not data[0]:
            return None

        uids = data[0].split()

        # Walk from most recent to oldest
        for uid in reversed(uids):
            status, msg_data = mail.fetch(uid, "(RFC822)")
            if status != "OK":
                continue

            msg = email.message_from_bytes(msg_data[0][1])

            # Check all possible recipient headers
            recipient_headers = []
            for header in ("To", "Cc", "Delivered-To", "X-Original-To", "X-Forwarded-To"):
                val = msg.get_all(header) or []
                recipient_headers.extend(val)

            combined = " ".join(recipient_headers).lower()

            if target_email in combined:
                return {
                    "sender":  _decode_str(msg.get("From", "")),
                    "date":    msg.get("Date", "Unknown"),
                    "subject": _decode_str(msg.get("Subject", "(no subject)")),
                    "body":    _get_body(msg),
                }

    return None
