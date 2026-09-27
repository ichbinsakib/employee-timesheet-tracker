"""Gmail API client (read-only).

OAuth files live on the desktop only, in the secrets folder:

    secrets/gmail_credentials.json   OAuth client ("Desktop app") downloaded from Google Cloud
    secrets/gmail_token.json         created by `python scripts/gmail_auth.py`

The app only requests `gmail.readonly`: it never sends, deletes or modifies mail.
Processed message IDs are tracked in the database instead of Gmail labels.
"""
from __future__ import annotations

import base64
import logging
from dataclasses import dataclass, field
from datetime import datetime
from email.utils import parseaddr

from backend.config import settings

log = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


class GmailNotConfigured(RuntimeError):
    pass


@dataclass
class Attachment:
    filename: str
    attachment_id: str | None
    inline_data: str | None
    size: int


@dataclass
class MessageInfo:
    message_id: str
    thread_id: str | None
    sender_email: str | None
    subject: str | None
    timestamp: datetime | None
    attachments: list[Attachment] = field(default_factory=list)


def status() -> dict:
    """What the Settings/Imports pages show about the Gmail connection."""
    info = {
        "credentials_file": str(settings.gmail_credentials_file),
        "token_file": str(settings.gmail_token_file),
        "credentials_present": settings.gmail_credentials_file.exists(),
        "token_present": settings.gmail_token_file.exists(),
        "connected": False,
        "account": None,
        "error": None,
    }
    if not info["token_present"]:
        info["error"] = "Gmail is not connected yet. Run scripts\\gmail_auth.bat on the desktop."
        return info
    try:
        creds = load_credentials()
        info["connected"] = creds is not None and creds.valid
    except Exception as exc:  # noqa: BLE001
        info["error"] = str(exc)
    return info


def load_credentials():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    token = settings.gmail_token_file
    if not token.exists():
        raise GmailNotConfigured("Gmail is not connected. Run scripts\\gmail_auth.bat on the desktop.")
    creds = Credentials.from_authorized_user_file(str(token), SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            token.write_text(creds.to_json(), encoding="utf-8")
        else:
            raise GmailNotConfigured("Gmail authorisation has expired. Run scripts\\gmail_auth.bat again.")
    return creds


def build_service():
    from googleapiclient.discovery import build

    return build("gmail", "v1", credentials=load_credentials(), cache_discovery=False)


def run_oauth_flow() -> str:
    """Interactive: opens a browser on the desktop. Used by scripts/gmail_auth.py."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not settings.gmail_credentials_file.exists():
        raise GmailNotConfigured(
            f"OAuth client file not found: {settings.gmail_credentials_file}\n"
            "Download it from Google Cloud Console (APIs & Services > Credentials > OAuth client ID > Desktop app)."
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(settings.gmail_credentials_file), SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")
    settings.gmail_token_file.parent.mkdir(parents=True, exist_ok=True)
    settings.gmail_token_file.write_text(creds.to_json(), encoding="utf-8")
    service = build_service()
    profile = service.users().getProfile(userId="me").execute()
    return profile.get("emailAddress", "")


# --------------------------------------------------------------------------- API wrappers
class GmailClient:
    """Thin wrapper so the sync logic can be tested with a fake service object."""

    def __init__(self, service=None):
        self.service = service or build_service()

    def list_message_ids(self, query: str, limit: int = 500) -> list[str]:
        ids: list[str] = []
        req = self.service.users().messages().list(userId="me", q=query, maxResults=100)
        while req is not None and len(ids) < limit:
            resp = req.execute()
            ids += [m["id"] for m in resp.get("messages", [])]
            req = self.service.users().messages().list_next(req, resp)
        return ids[:limit]

    def get_message(self, message_id: str) -> MessageInfo:
        msg = self.service.users().messages().get(userId="me", id=message_id, format="full").execute()
        payload = msg.get("payload", {})
        headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}
        ts = None
        if msg.get("internalDate"):
            ts = datetime.fromtimestamp(int(msg["internalDate"]) / 1000).replace(microsecond=0)
        info = MessageInfo(
            message_id=msg["id"], thread_id=msg.get("threadId"),
            sender_email=(parseaddr(headers.get("from", ""))[1] or None),
            subject=headers.get("subject"), timestamp=ts,
        )
        for part in _walk_parts(payload):
            filename = part.get("filename")
            if filename:
                body = part.get("body", {})
                info.attachments.append(Attachment(
                    filename=filename, attachment_id=body.get("attachmentId"),
                    inline_data=body.get("data"), size=int(body.get("size", 0) or 0),
                ))
        return info

    def download(self, message_id: str, att: Attachment) -> bytes:
        data = att.inline_data
        if data is None and att.attachment_id:
            resp = self.service.users().messages().attachments().get(
                userId="me", messageId=message_id, id=att.attachment_id).execute()
            data = resp.get("data", "")
        return base64.urlsafe_b64decode((data or "").encode("ascii") + b"==")


def _walk_parts(part: dict):
    yield part
    for sub in part.get("parts", []) or []:
        yield from _walk_parts(sub)
