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
ALLOWED_SENDERS = ["noreply@tm.openai.com", "noreply@tm1.openai.com", "otp@tm1.openai.com", "otp@tm.openai.com"]
IMAP_USER = os.getenv("IMAP_USER")
IMAP_PASS = os.getenv("IMAP_PASS")


# ─────────────────────────────────────────────
# Persistent IMAP connection pool
# ─────────────────────────────────────────────

class IMAPConnectionPool:
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
        if target_email in " ".join(val).lower():
            return True
    if target_email in _get_body(msg).lower():
        logger.info("Matched %s via body fallback", target_email)
        return True
    return False


# ─────────────────────────────────────────────
# Main fetch function
# ─────────────────────────────────────────────

def fetch_latest_email_for_address(target_email: str, imap_user: str = None, imap_pass: str = None):
    target_email = target_email.lower().strip()
    logger.info("Fetching email for: %s", target_email)

    if imap_user or imap_pass:
        return _fetch_with_fresh_connection(target_email, imap_user or IMAP_USER, imap_pass or IMAP_PASS)

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
    # Step 1: collect all UIDs from allowed senders
    uids_set = set()
    for sender in ALLOWED_SENDERS:
        status, data = mail.search(None, f'FROM "{sender}"')
        if status == "OK" and data[0]:
            uids_set.update(data[0].split())

    if not uids_set:
        logger.warning("No emails found from any allowed sender")
        return None

    # Sort descending (newest first)
    uids = sorted(uids_set, key=lambda x: int(x), reverse=True)
    logger.info("Found %d emails, scanning for %s", len(uids), target_email)

    # Step 2: fetch headers only in one batch to find candidates fast
    uid_str = b",".join(uids)
    status, hdr_data = mail.fetch(
        uid_str,
        "(UID BODY.PEEK[HEADER.FIELDS (TO CC DELIVERED-TO X-ORIGINAL-TO X-FORWARDED-TO)])"
    )
    if status != "OK":
        logger.warning("Batch header fetch failed")
        return None

    # Step 3: parse header responses and find matching UIDs (newest first)
    candidate_uids = []
    i = 0
    while i < len(hdr_data):
        item = hdr_data[i]
        if isinstance(item, tuple):
            meta = item[0].decode() if isinstance(item[0], bytes) else item[0]
            raw_hdr = item[1].decode("utf-8", errors="replace").lower() if isinstance(item[1], bytes) else item[1].lower()
            # extract UID from meta like "86 (UID 86 BODY[HEADER..."
            uid_match = re.search(r'uid (\d+)', meta, re.IGNORECASE)
            uid = uid_match.group(1).encode() if uid_match else None
            if uid and target_email in raw_hdr:
                candidate_uids.append(uid)
        i += 1

    # Sort candidates descending so we check newest first
    candidate_uids.sort(key=lambda x: int(x), reverse=True)
    logger.info("Header candidates for %s: %s", target_email, candidate_uids)

    # Step 4: fetch full body only for candidates
    for uid in candidate_uids:
        status, msg_data = mail.fetch(uid, "(RFC822)")
        if status != "OK":
            continue
        msg = email.message_from_bytes(msg_data[0][1])
        if _email_matches(msg, target_email):
            logger.info("Match confirmed at UID %s", uid)
            return {
                "sender":  _decode_str(msg.get("From", "")),
                "date":    msg.get("Date", "Unknown"),
                "subject": _decode_str(msg.get("Subject", "(no subject)")),
                "body":    _get_body(msg),
            }

    # Step 5: fallback — body scan for catch-all inboxes that strip headers
    logger.info("No header match, doing body fallback scan")
    for uid in uids:
        if uid in candidate_uids:
            continue  # already checked
        status, msg_data = mail.fetch(uid, "(RFC822)")
        if status != "OK":
            continue
        msg = email.message_from_bytes(msg_data[0][1])
        if _email_matches(msg, target_email):
            logger.info("Body fallback match at UID %s", uid)
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
