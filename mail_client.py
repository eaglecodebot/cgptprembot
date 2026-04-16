import imaplib
import email
import re
import logging
import socket
from email.header import decode_header

import os
from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)

IMAP_HOST = os.getenv("IMAP_HOST", "imap.gmail.com")
IMAP_PORT = int(os.getenv("IMAP_PORT", "993"))
IMAP_MAILBOX = os.getenv("IMAP_MAILBOX", "INBOX")
IMAP_TIMEOUT = int(os.getenv("IMAP_TIMEOUT", "8"))
ALLOWED_SENDERS = [
    "noreply@tm.openai.com",
    "noreply@tm1.openai.com",
    "otp@tm1.openai.com",
    "otp@tm.openai.com",
]
IMAP_USER = os.getenv("IMAP_USER")
IMAP_PASS = os.getenv("IMAP_PASS")

# How aggressively to narrow search before falling back wider.
RECENT_UID_LIMIT = int(os.getenv("IMAP_RECENT_UID_LIMIT", "80"))
MEDIUM_UID_LIMIT = int(os.getenv("IMAP_MEDIUM_UID_LIMIT", "200"))
MAX_BODY_FALLBACK = int(os.getenv("IMAP_MAX_BODY_FALLBACK", "25"))


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
    html = re.sub(r'(?i)<br\s*/?>', '\n', html)
    html = re.sub(r'(?i)</p>|</div>|</tr>|</table>|</li>', '\n', html)
    clean = re.sub(r"<[^>]+>", " ", html)
    clean = re.sub(r"[ \t\r\f\v]+", " ", clean)
    clean = re.sub(r"\n+", "\n", clean)
    return clean.strip()


def _decode_part_payload(part):
    payload = part.get_payload(decode=True)
    if payload is None:
        raw = part.get_payload()
        return raw if isinstance(raw, str) else ""
    charset = part.get_content_charset() or "utf-8"
    return payload.decode(charset, errors="replace")


def _get_body(msg):
    plain_parts = []
    html_parts = []

    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            disp = str(part.get("Content-Disposition", "")).lower()
            if "attachment" in disp:
                continue
            try:
                text = _decode_part_payload(part).strip()
            except Exception:
                continue
            if not text:
                continue
            if ct == "text/plain":
                plain_parts.append(text)
            elif ct == "text/html":
                html_parts.append(_strip_html(text))
    else:
        try:
            text = _decode_part_payload(msg).strip()
        except Exception:
            return ""
        if msg.get_content_type() == "text/html":
            return _strip_html(text)
        return text

    def score(text: str) -> tuple[int, int]:
        has_code = 1 if re.search(r'(?<!\d)\d{6}(?!\d)', text) else 0
        return (has_code, len(text))

    if plain_parts:
        plain_parts.sort(key=score, reverse=True)
        return plain_parts[0]
    if html_parts:
        html_parts.sort(key=score, reverse=True)
        return html_parts[0]
    return ""


def _email_matches(msg, target_email: str) -> bool:
    target_email = target_email.lower()
    for header in ("To", "Cc", "Delivered-To", "X-Original-To", "X-Forwarded-To"):
        values = msg.get_all(header) or []
        if target_email in " ".join(values).lower():
            return True
    body = _get_body(msg).lower()
    if target_email in body:
        logger.info("Matched %s via body fallback", target_email)
        return True
    return False


def _extract_uid_from_meta(meta) -> bytes | None:
    meta_text = meta.decode() if isinstance(meta, bytes) else str(meta)
    uid_match = re.search(r'uid (\d+)', meta_text, re.IGNORECASE)
    return uid_match.group(1).encode() if uid_match else None


def _collect_sender_uids(mail):
    uids_set = set()
    for sender in ALLOWED_SENDERS:
        status, data = mail.search(None, f'FROM "{sender}"')
        if status == "OK" and data and data[0]:
            uids_set.update(data[0].split())
    return sorted(uids_set, key=lambda x: int(x), reverse=True)


def _find_candidate_uids(mail, uids, target_email: str):
    if not uids:
        return []

    uid_str = b",".join(uids)
    status, hdr_data = mail.fetch(
        uid_str,
        "(UID BODY.PEEK[HEADER.FIELDS (TO CC DELIVERED-TO X-ORIGINAL-TO X-FORWARDED-TO SUBJECT)])"
    )
    if status != "OK":
        logger.warning("Batch header fetch failed")
        return []

    candidates = []
    for item in hdr_data:
        if not isinstance(item, tuple):
            continue
        uid = _extract_uid_from_meta(item[0])
        if not uid:
            continue
        raw_hdr = item[1].decode("utf-8", errors="replace").lower() if isinstance(item[1], bytes) else str(item[1]).lower()
        if target_email in raw_hdr:
            candidates.append(uid)

    candidates.sort(key=lambda x: int(x), reverse=True)
    return candidates


def _fetch_message(mail, uid):
    status, msg_data = mail.fetch(uid, "(RFC822)")
    if status != "OK" or not msg_data or not isinstance(msg_data[0], tuple):
        return None
    return email.message_from_bytes(msg_data[0][1])


def _build_result(msg):
    return {
        "sender": _decode_str(msg.get("From", "")),
        "date": msg.get("Date", "Unknown"),
        "subject": _decode_str(msg.get("Subject", "(no subject)")),
        "body": _get_body(msg),
    }


def _do_fetch(mail, target_email: str):
    all_uids = _collect_sender_uids(mail)
    if not all_uids:
        logger.warning("No emails found from any allowed sender")
        return None

    logger.info("Found %d emails, scanning for %s", len(all_uids), target_email)

    windows = []
    recent = all_uids[:RECENT_UID_LIMIT]
    medium = all_uids[:MEDIUM_UID_LIMIT]
    windows.append(("recent", recent))
    if medium != recent:
        windows.append(("medium", medium))
    if all_uids != medium:
        windows.append(("full", all_uids))

    seen_candidate_uids = set()

    for label, window_uids in windows:
        candidate_uids = _find_candidate_uids(mail, window_uids, target_email)
        new_candidates = [uid for uid in candidate_uids if uid not in seen_candidate_uids]
        seen_candidate_uids.update(new_candidates)
        logger.info("Header candidates for %s (%s scan): %s", target_email, label, new_candidates)

        for uid in new_candidates:
            msg = _fetch_message(mail, uid)
            if not msg:
                continue
            if _email_matches(msg, target_email):
                logger.info("Match confirmed at UID %s", uid)
                return _build_result(msg)

    logger.info("No header match, doing limited body fallback scan")
    fallback_uids = [uid for uid in all_uids if uid not in seen_candidate_uids][:MAX_BODY_FALLBACK]
    for uid in fallback_uids:
        msg = _fetch_message(mail, uid)
        if not msg:
            continue
        if _email_matches(msg, target_email):
            logger.info("Body fallback match at UID %s", uid)
            return _build_result(msg)

    logger.warning("No email matched recipient: %s", target_email)
    return None


def _fetch_with_fresh_connection(target_email: str, imap_user: str, imap_pass: str):
    socket.setdefaulttimeout(IMAP_TIMEOUT)
    with imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, timeout=IMAP_TIMEOUT) as mail:
        mail.login(imap_user, imap_pass)
        mail.select(IMAP_MAILBOX, readonly=True)
        return _do_fetch(mail, target_email)


def fetch_latest_email_for_address(target_email: str, imap_user: str = None, imap_pass: str = None):
    target_email = target_email.lower().strip()
    logger.info("Fetching email for: %s", target_email)
    return _fetch_with_fresh_connection(target_email, imap_user or IMAP_USER, imap_pass or IMAP_PASS)
