"""Email MCP Server — read emails via IMAP, send via SMTP.

Connects to any standard email account (Gmail, Outlook, Infomaniak,
ProtonMail Bridge, self-hosted, …) and exposes tools for reading,
searching, and sending email.
"""

from __future__ import annotations

import email
import email.header
import email.utils
import os
import re
import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from imaplib import IMAP4_SSL

from fastmcp import FastMCP

mcp = FastMCP("Email MCP")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

IMAP_HOST = os.environ.get("IMAP_HOST", "").strip()
IMAP_PORT = int(os.environ.get("IMAP_PORT", "993"))
SMTP_HOST = os.environ.get("SMTP_HOST", "").strip()
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
EMAIL_USER = os.environ.get("EMAIL_USER", "").strip()
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "").strip()
EMAIL_FROM = os.environ.get("EMAIL_FROM", "").strip() or EMAIL_USER

MAX_RESULTS = int(os.environ.get("MAX_RESULTS", "25"))
ALLOW_SEND = os.environ.get("ALLOW_SEND", "").lower() in ("1", "true", "yes")
ALLOW_DELETE = os.environ.get("ALLOW_DELETE", "").lower() in ("1", "true", "yes")

# ---------------------------------------------------------------------------
# IMAP helpers
# ---------------------------------------------------------------------------


def _imap() -> IMAP4_SSL:
    """Open an authenticated IMAP connection."""
    conn = IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    conn.login(EMAIL_USER, EMAIL_PASSWORD)
    return conn


def _decode_header(raw: str | None) -> str:
    """Decode RFC‑2047 encoded header value."""
    if not raw:
        return ""
    parts = email.header.decode_header(raw)
    decoded: list[str] = []
    for data, charset in parts:
        if isinstance(data, bytes):
            decoded.append(data.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(data)
    return " ".join(decoded)


def _extract_text(msg: email.message.Message) -> str:
    """Extract plain‑text body from a message (or convert HTML fallback)."""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    return payload.decode(charset, errors="replace")
        # Fallback: first text/html
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/html":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    html = payload.decode(charset, errors="replace")
                    return _strip_html(html)
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="replace")
            if msg.get_content_type() == "text/html":
                return _strip_html(text)
            return text
    return ""


def _strip_html(html: str) -> str:
    """Rudimentary HTML→text conversion."""
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _parse_date(msg: email.message.Message) -> str:
    """Parse the Date header into ISO format."""
    raw = msg.get("Date", "")
    try:
        dt = email.utils.parsedate_to_datetime(raw)
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        return raw


def _summarize(msg: email.message.Message, uid: str) -> dict:
    """Return a compact dict for a single message."""
    return {
        "uid": uid,
        "from": _decode_header(msg.get("From")),
        "to": _decode_header(msg.get("To")),
        "subject": _decode_header(msg.get("Subject")),
        "date": _parse_date(msg),
    }


def _fetch_uids(conn: IMAP4_SSL, mailbox: str, search_criteria: str, limit: int) -> list[str]:
    """Select a mailbox, search, and return UIDs (newest first)."""
    conn.select(mailbox, readonly=True)
    _status, data = conn.uid("SEARCH", None, search_criteria)
    uids = data[0].split() if data[0] else []
    # Newest first, limited
    return list(reversed(uids))[:limit]


def _fetch_messages(conn: IMAP4_SSL, uids: list[str], body: bool = False) -> list[dict]:
    """Fetch messages by UID. If body=False, fetch headers only."""
    results = []
    parts = "(BODY.PEEK[HEADER] FLAGS)" if not body else "(BODY.PEEK[] FLAGS)"
    for uid in uids:
        _status, data = conn.uid("FETCH", uid, parts)
        if not data or data[0] is None:
            continue
        raw = data[0][1] if isinstance(data[0], tuple) else data[0]
        msg = email.message_from_bytes(raw)
        info = _summarize(msg, uid.decode() if isinstance(uid, bytes) else uid)
        # Check flags for read/unread
        flag_data = data[0][0] if isinstance(data[0], tuple) else b""
        info["unread"] = b"\\Seen" not in flag_data
        if body:
            info["body"] = _extract_text(msg)
            # Attachments info
            attachments = []
            if msg.is_multipart():
                for part in msg.walk():
                    fn = part.get_filename()
                    if fn:
                        attachments.append(_decode_header(fn))
            info["attachments"] = attachments
        results.append(info)
    return results


# ---------------------------------------------------------------------------
# Read tools
# ---------------------------------------------------------------------------


@mcp.tool()
def list_mailboxes() -> list[dict]:
    """List all mailbox folders (Inbox, Sent, Drafts, Trash, …)."""
    conn = _imap()
    try:
        _status, data = conn.list()
        mailboxes = []
        for item in data:
            if not item:
                continue
            decoded = item.decode() if isinstance(item, bytes) else item
            # Parse: (\\Flags) "/" "Mailbox Name"
            match = re.search(r'"([^"]*)"$|(\S+)$', decoded)
            if match:
                name = match.group(1) or match.group(2)
                mailboxes.append({"name": name, "raw": decoded})
        return mailboxes
    finally:
        conn.logout()


@mcp.tool()
def get_inbox(limit: int = 20) -> list[dict]:
    """Get the most recent emails from the inbox.

    Args:
        limit: Maximum number of emails to return (default: 20).
    """
    limit = min(limit, MAX_RESULTS)
    conn = _imap()
    try:
        uids = _fetch_uids(conn, "INBOX", "ALL", limit)
        return _fetch_messages(conn, uids)
    finally:
        conn.logout()


@mcp.tool()
def get_unread(limit: int = 20) -> list[dict]:
    """Get unread emails from the inbox.

    Args:
        limit: Maximum number of emails to return (default: 20).
    """
    limit = min(limit, MAX_RESULTS)
    conn = _imap()
    try:
        uids = _fetch_uids(conn, "INBOX", "UNSEEN", limit)
        return _fetch_messages(conn, uids)
    finally:
        conn.logout()


@mcp.tool()
def get_unread_count() -> dict:
    """Get the number of unread emails in the inbox."""
    conn = _imap()
    try:
        conn.select("INBOX", readonly=True)
        _status, data = conn.uid("SEARCH", None, "UNSEEN")
        uids = data[0].split() if data[0] else []
        return {"unread": len(uids)}
    finally:
        conn.logout()


@mcp.tool()
def read_email(uid: str) -> dict:
    """Read a specific email by UID. Returns full body and attachments.

    Args:
        uid: The UID of the email to read.
    """
    conn = _imap()
    try:
        conn.select("INBOX", readonly=True)
        msgs = _fetch_messages(conn, [uid.encode()], body=True)
        if not msgs:
            return {"error": f"Email {uid} not found"}
        return msgs[0]
    finally:
        conn.logout()


@mcp.tool()
def search_emails(query: str, mailbox: str = "INBOX", limit: int = 20) -> list[dict]:
    """Search emails by keyword in subject, sender, or body.

    Args:
        query: Search term.
        mailbox: Mailbox folder to search (default: INBOX).
        limit: Maximum number of results (default: 20).
    """
    limit = min(limit, MAX_RESULTS)
    conn = _imap()
    try:
        conn.select(mailbox, readonly=True)
        # Search in subject, from, and body
        results = []
        for criteria in [
            f'(SUBJECT "{query}")',
            f'(FROM "{query}")',
            f'(BODY "{query}")',
        ]:
            _status, data = conn.uid("SEARCH", None, criteria)
            if data[0]:
                results.extend(data[0].split())
        # Deduplicate, newest first
        seen = set()
        unique_uids = []
        for uid in reversed(results):
            if uid not in seen:
                seen.add(uid)
                unique_uids.append(uid)
        unique_uids = unique_uids[:limit]
        return _fetch_messages(conn, unique_uids)
    finally:
        conn.logout()


@mcp.tool()
def get_emails_from(mailbox: str = "Sent", limit: int = 20) -> list[dict]:
    """Get emails from a specific mailbox folder (Sent, Drafts, Trash, …).

    Args:
        mailbox: Mailbox folder name (default: Sent).
        limit: Maximum number of emails to return (default: 20).
    """
    limit = min(limit, MAX_RESULTS)
    conn = _imap()
    try:
        uids = _fetch_uids(conn, mailbox, "ALL", limit)
        return _fetch_messages(conn, uids)
    finally:
        conn.logout()


# ---------------------------------------------------------------------------
# Action tools
# ---------------------------------------------------------------------------


@mcp.tool()
def mark_as_read(uid: str) -> dict:
    """Mark an email as read.

    Args:
        uid: The UID of the email to mark as read.
    """
    conn = _imap()
    try:
        conn.select("INBOX")
        conn.uid("STORE", uid.encode(), "+FLAGS", "\\Seen")
        return {"success": True, "uid": uid}
    finally:
        conn.logout()


@mcp.tool()
def mark_as_unread(uid: str) -> dict:
    """Mark an email as unread.

    Args:
        uid: The UID of the email to mark as unread.
    """
    conn = _imap()
    try:
        conn.select("INBOX")
        conn.uid("STORE", uid.encode(), "-FLAGS", "\\Seen")
        return {"success": True, "uid": uid}
    finally:
        conn.logout()


if ALLOW_SEND:

    @mcp.tool()
    def send_email(to: str, subject: str, body: str, cc: str = "", bcc: str = "") -> dict:
        """Send an email.

        Args:
            to: Recipient email address(es), comma-separated for multiple.
            subject: Email subject.
            body: Email body (plain text).
            cc: CC recipients, comma-separated (optional).
            bcc: BCC recipients, comma-separated (optional).
        """
        msg = MIMEMultipart()
        msg["From"] = EMAIL_FROM
        msg["To"] = to
        msg["Subject"] = subject
        if cc:
            msg["Cc"] = cc
        msg.attach(MIMEText(body, "plain", "utf-8"))

        all_recipients = [a.strip() for a in to.split(",")]
        if cc:
            all_recipients += [a.strip() for a in cc.split(",")]
        if bcc:
            all_recipients += [a.strip() for a in bcc.split(",")]

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(EMAIL_USER, EMAIL_PASSWORD)
            smtp.sendmail(EMAIL_FROM, all_recipients, msg.as_string())

        return {"success": True, "to": to, "subject": subject}

    @mcp.tool()
    def reply_to_email(uid: str, body: str) -> dict:
        """Reply to an email by UID.

        Args:
            uid: The UID of the email to reply to.
            body: Reply body (plain text).
        """
        # Fetch original
        conn = _imap()
        try:
            conn.select("INBOX", readonly=True)
            msgs = _fetch_messages(conn, [uid.encode()], body=True)
            if not msgs:
                return {"error": f"Email {uid} not found"}
            original = msgs[0]
        finally:
            conn.logout()

        to = original["from"]
        subject = original["subject"]
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"

        msg = MIMEMultipart()
        msg["From"] = EMAIL_FROM
        msg["To"] = to
        msg["Subject"] = subject
        msg["In-Reply-To"] = uid
        msg.attach(MIMEText(body, "plain", "utf-8"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(EMAIL_USER, EMAIL_PASSWORD)
            smtp.sendmail(EMAIL_FROM, [to], msg.as_string())

        return {"success": True, "to": to, "subject": subject}


if ALLOW_DELETE:

    @mcp.tool()
    def delete_email(uid: str) -> dict:
        """Delete an email by UID (moves to Trash).

        Args:
            uid: The UID of the email to delete.
        """
        conn = _imap()
        try:
            conn.select("INBOX")
            conn.uid("STORE", uid.encode(), "+FLAGS", "\\Deleted")
            conn.expunge()
            return {"success": True, "uid": uid}
        finally:
            conn.logout()
