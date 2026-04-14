import imaplib
import email
import re
import logging
import threading
from email.header import decode_header

import os
from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)

IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993
IMAP_MAILBOX = "INBOX"
ALLOWED_SENDERS = ["noreply@tm.openai.com", "noreply@tm1.openai.com"]
IMAP_USER = os.getenv("IMAP_USER")
IMAP_PASS = os.getenv("IMAP_PASS")


# ─────────────────────────────────────────────
# Persistent IMAP connection
# ─────────────────────────────────────────────

class IMAPConnectionPool:
    """Keeps a single persistent IMAP connection alive and reconnects if dropped."""

    def __init__(self):
        self._conn = None
        self._lock = threading.Lock()

    def _connect(self):
        logger.info("Opening new IMAP connection…")
        conn = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
        conn.login(IMAP_USER, IMAP_PASS)
        conn.select(IMAP_MAILBOX, readonly=True)
        return conn

    def get(self) -> imaplib.IMAP4_SSL:
        with self._lock:
            if self._conn is None:
                self._conn = self._connect()
                return self._conn
            # NOOP to check if connection is still alive
            try:
                self._conn.noop()
            except Exception:
                logger.warning("IMAP connection dropped, reconnecting…")
                try:
                    self._conn.logout()
                except Exception:
                    pass
                self._conn = self._connect()
            return self._conn

    def invalidate(self):
        with self._lock:
            if self._conn:
                try:
                    self._conn.logout()
                except Exception:
                    pass
                self._conn = None


_pool = IMAPConnectionPool()


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

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


def _email_matches(msg, target_email: str) -> bool:
    for header in ("To", "Cc", "Delivered-To", "X-Original-To", "X-Forwarded-To"):
        val = msg.get_all(header) or []
        combined = " ".join(val).lower()
        if target_email in combined:
            return True
    body = _get_body(msg).lower()
    if target_email in body:
        logger.info("Matched %s via body fallback", target_email)
        return True
    return False


# ─────────────────────────────────────────────
# Main fetch function
# ─────────────────────────────────────────────

def fetch_latest_email_for_address(target_email: str, imap_user: str = None, imap_pass: str = None):
    target_email = target_email.lower().strip()
    logger.info("Fetching email for: %s", target_email)

    # If custom credentials provided, use a fresh connection (not the pool)
    if imap_user or imap_pass:
        return _fetch_with_fresh_connection(target_email, imap_user or IMAP_USER, imap_pass or IMAP_PASS)

    # Try up to 2 times in case connection dropped mid-request
    for attempt in range(2):
        try:
            mail = _pool.get()
            return _do_fetch(mail, target_email)
        except Exception as e:
            logger.warning("IMAP fetch attempt %d failed: %s", attempt + 1, e)
            _pool.invalidate()
            if attempt == 1:
                raise

    return None


def _do_fetch(mail, target_email: str):
    uids_set = set()
    for sender in ALLOWED_SENDERS:
        status, data = mail.search(None, f'FROM "{sender}"')
        if status == "OK" and data[0]:
            uids_set.update(data[0].split())

    if not uids_set:
        logger.warning("No emails found from any allowed sender")
        return None

    uids = sorted(uids_set, key=lambda x: int(x))
    logger.info("Found %d emails total, scanning for %s", len(uids), target_email)

    for uid in reversed(uids):
        status, msg_data = mail.fetch(uid, "(RFC822)")
        if status != "OK":
            continue
        msg = email.message_from_bytes(msg_data[0][1])
        logger.info("UID %s — To: %s", uid, msg.get("To", ""))
        if _email_matches(msg, target_email):
            logger.info("Match found at UID %s", uid)
            return {
                "sender":  _decode_str(msg.get("From", "")),
                "date":    msg.get("Date", "Unknown"),
                "subject": _decode_str(msg.get("Subject", "(no subject)")),
                "body":    _get_body(msg),
            }

    logger.warning("No email matched recipient: %s", target_email)
    return None


def _fetch_with_fresh_connection(target_email: str, imap_user: str, imap_pass: str):
    with imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT) as mail:
        mail.login(imap_user, imap_pass)
        mail.select(IMAP_MAILBOX, readonly=True)
        return _do_fetch(mail, target_email)
