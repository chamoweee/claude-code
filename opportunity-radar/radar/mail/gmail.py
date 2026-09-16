"""Sending mail through the Gmail API.

Implemented against the REST endpoints with nothing but the standard library.
``google-api-python-client`` pulls in a large dependency tree for what is, in
the end, two HTTP calls: swap a refresh token for an access token, then POST a
base64url-encoded MIME message.

Scope is ``gmail.send`` only. The agent has no ability to read mail, and the
credentials it holds cannot be used to.

Credentials come from the environment (GitHub Secrets in CI) and are never
written to disk, never logged, and never included in an error message.
"""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

TOKEN_URL = "https://oauth2.googleapis.com/token"
SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
TIMEOUT = 30.0


class MailError(RuntimeError):
    """Sending failed. The message never contains credentials."""


@dataclass(frozen=True)
class GmailCredentials:
    client_id: str
    client_secret: str
    refresh_token: str
    sender: str

    @classmethod
    def from_env(cls) -> "GmailCredentials":
        missing = [name for name in
                   ("GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET",
                    "GMAIL_REFRESH_TOKEN", "GMAIL_SENDER")
                   if not os.environ.get(name)]
        if missing:
            raise MailError(
                "Gmail is not configured. Missing: " + ", ".join(missing) +
                ". See README.md § Gmail API.")
        return cls(
            client_id=os.environ["GMAIL_CLIENT_ID"],
            client_secret=os.environ["GMAIL_CLIENT_SECRET"],
            refresh_token=os.environ["GMAIL_REFRESH_TOKEN"],
            sender=os.environ["GMAIL_SENDER"],
        )

    def __repr__(self) -> str:  # pragma: no cover - defensive
        return f"GmailCredentials(sender={self.sender!r}, secrets hidden)"


def build_message(*, sender: str, recipient: str, subject: str,
                  html: str, text: str) -> EmailMessage:
    """A multipart/alternative message: plain text first, then HTML.

    The text part is a real alternative, not a placeholder — some clients show
    it, and it is what survives forwarding into a thread.
    """
    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = subject
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid(domain="opportunity-radar.local")
    # This is a machine-generated report; keep it out of auto-responder loops.
    message["Auto-Submitted"] = "auto-generated"
    message["X-Auto-Response-Suppress"] = "All"
    message.set_content(text)
    message.add_alternative(html, subtype="html")
    return message


def _post_form(url: str, fields: dict[str, str]) -> dict:
    data = urllib.parse.urlencode(fields).encode()
    request = urllib.request.Request(url, data=data, method="POST")
    request.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        raise MailError(_describe(exc, "token exchange")) from None
    except (urllib.error.URLError, OSError) as exc:
        raise MailError(f"token exchange failed: {type(exc).__name__}") from None


def _describe(exc: urllib.error.HTTPError, stage: str) -> str:
    """Turn a Google error into something actionable, without echoing secrets."""
    try:
        detail = json.loads(exc.read().decode())
    except Exception:  # noqa: BLE001 - best effort only
        detail = {}
    code = detail.get("error", "")
    if code == "invalid_grant":
        return (f"{stage} failed: the Gmail refresh token is invalid or revoked. "
                f"Re-run `python -m radar.mail.authorize` and update "
                f"GMAIL_REFRESH_TOKEN.")
    if code == "invalid_client":
        return (f"{stage} failed: GMAIL_CLIENT_ID or GMAIL_CLIENT_SECRET does not "
                f"match an OAuth client.")
    message = (detail.get("error_description")
               or (detail.get("error", {}) or {}).get("message")
               if isinstance(detail.get("error"), dict) else detail.get("error_description"))
    return f"{stage} failed: HTTP {exc.code} {message or ''}".strip()


def access_token(credentials: GmailCredentials) -> str:
    payload = _post_form(TOKEN_URL, {
        "client_id": credentials.client_id,
        "client_secret": credentials.client_secret,
        "refresh_token": credentials.refresh_token,
        "grant_type": "refresh_token",
    })
    token = payload.get("access_token")
    if not token:
        raise MailError("token exchange returned no access token")
    return token


def send(message: EmailMessage, credentials: GmailCredentials,
         token: str | None = None) -> str:
    """Send one message. Returns the Gmail message id."""
    token = token or access_token(credentials)
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    request = urllib.request.Request(
        SEND_URL, data=json.dumps({"raw": raw}).encode(), method="POST")
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.loads(response.read().decode()).get("id", "")
    except urllib.error.HTTPError as exc:
        raise MailError(_describe(exc, "send")) from None
    except (urllib.error.URLError, OSError) as exc:
        raise MailError(f"send failed: {type(exc).__name__}") from None


def send_email(*, recipient: str, subject: str, html: str, text: str,
               credentials: GmailCredentials | None = None,
               sender_fn=send) -> str:
    credentials = credentials or GmailCredentials.from_env()
    message = build_message(sender=credentials.sender, recipient=recipient,
                            subject=subject, html=html, text=text)
    return sender_fn(message, credentials)
