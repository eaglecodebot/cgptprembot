import imaplib
import email
import re
import logging
from email.header import decode_header
from email.utils import parseaddr

import os
from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)

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
    target_email = target_email.lower().strip()

    logger.info("Fetching email for: %s", target_email)

    with imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT) as mail:
        mail.login(imap_user, imap_pass)
        mail.select(IMAP_MAILBOX, readonly=True)

        status, data = mail.search(None, f'FROM "{ALLOWED_SENDER}"')
        if status != "OK" or not data[0]:
            logger.warning("No emails found from sender: %s", ALLOWED_SENDER)
            return None

        uids = data[0].split()
        logger.info("Found %d emails from sender, scanning for %s", len(uids), target_email)

        # Fetch only headers first (fast) to find the right email
        for uid in reversed(uids):
            status, hdr_data = mail.fetch(
                uid,
                "(BODY.PEEK[HEADER.FIELDS (TO CC DELIVERED-TO X-ORIGINAL-TO X-FORWARDED-TO)])"
            )
            if status != "OK":
                continue

            raw_headers = hdr_data[0][1].decode("utf-8", errors="replace").lower()
            logger.info("UID %s headers: %s", uid, raw_headers.strip())

            if target_email in raw_headers:
                logger.info("Match found at UID %s, fetching full email", uid)
                status, msg_data = mail.fetch(uid, "(RFC822)")
                if status != "OK":
                    continue
                msg = email.message_from_bytes(msg_data[0][1])
                return {
                    "sender":  _decode_str(msg.get("From", "")),
                    "date":    msg.get("Date", "Unknown"),
                    "subject": _decode_str(msg.get("Subject", "(no subject)")),
                    "body":    _get_body(msg),
                }

        logger.warning("No email matched recipient: %s", target_email)
    return None
