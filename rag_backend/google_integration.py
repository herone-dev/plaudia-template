"""Google Docs export + Gmail send/draft, shared by the Plaudia backend.

Reuses the same OAuth token already authorized for Hérone's Google Workspace
(scopes: documents, drive, gmail.send, gmail.modify — all already granted,
verified before building this). No separate auth flow per user; this backend
acts as the single Hérone service account, consistent with how it already
reads/writes Supabase under martin@herone.fr.
"""
import base64
import json
import re
from email.mime.text import MIMEText
from pathlib import Path

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

TOKEN_PATH = Path("/opt/data/google_token.json")


def _get_credentials():
    data = json.loads(TOKEN_PATH.read_text())
    scopes = data.get("scopes") or [
        "https://www.googleapis.com/auth/documents",
        "https://www.googleapis.com/auth/drive",
        "https://www.googleapis.com/auth/gmail.send",
        "https://www.googleapis.com/auth/gmail.modify",
    ]
    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), scopes)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN_PATH.write_text(json.dumps(json.loads(creds.to_json()), indent=2))
    return creds


def _docs_service():
    return build("docs", "v1", credentials=_get_credentials())


def _drive_service():
    return build("drive", "v3", credentials=_get_credentials())


def _gmail_service():
    return build("gmail", "v1", credentials=_get_credentials())


# --- CR HTML -> plain structured text, good enough for a first Google Docs export. ---
# Not a full HTML->Docs-API-requests renderer (no bold/colored table cells) — headings
# and paragraph breaks are preserved, which covers what the CR structure actually needs
# for a "send this as a real document" use case. Rich formatting is a possible follow-up,
# not built here.

def _strip_tags(html: str) -> str:
    text = re.sub(r"<[^>]+>", "", html)
    for a, b in [("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&#39;", "'"), ("&nbsp;", " ")]:
        text = text.replace(a, b)
    return text


def cr_html_to_doc_text(html: str) -> str:
    lines = []
    subtitle_m = re.search(r'<p class="cr-subtitle">(.*?)</p>', html, re.DOTALL)
    if subtitle_m:
        lines.append(_strip_tags(subtitle_m.group(1)).strip())
        lines.append("")

    meta_m = re.search(r"<dl class=\"cr-meta\">(.*?)</dl>", html, re.DOTALL)
    if meta_m:
        pairs = re.findall(r"<dt>(.*?)</dt>\s*<dd>(.*?)</dd>", meta_m.group(1), re.DOTALL)
        for label, value in pairs:
            lines.append(f"{_strip_tags(label).strip()} : {_strip_tags(value).strip()}")
        lines.append("")

    for section in re.findall(r'<section class="cr-section">(.*?)</section>', html, re.DOTALL):
        title_m = re.search(r'<h2 class="cr-section-title">(.*?)</h2>', section, re.DOTALL)
        if title_m:
            lines.append(_strip_tags(title_m.group(1)).strip().upper())

        if '<table class="cr-table"' in section:
            rows = re.findall(
                r'<td class="cr-table-label[^"]*">(.*?)</td>\s*<td class="cr-table-content">(.*?)</td>',
                section, re.DOTALL,
            )
            for label, content in rows:
                lines.append(f"  - {_strip_tags(label).strip()} : {_strip_tags(content).strip()}")
        else:
            for para in re.findall(r'<p class="cr-body">(.*?)</p>', section, re.DOTALL):
                lines.append(_strip_tags(para).strip())
            for item in re.findall(r"<li>(.*?)</li>", section, re.DOTALL):
                lines.append(f"  - {_strip_tags(item).strip()}")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def export_cr_to_google_doc(title: str, cr_html: str) -> dict:
    """Creates a new Google Doc with the CR content, returns {documentId, url}."""
    docs = _docs_service()
    doc = docs.documents().create(body={"title": title}).execute()
    doc_id = doc["documentId"]

    text = cr_html_to_doc_text(cr_html)
    docs.documents().batchUpdate(
        documentId=doc_id,
        body={"requests": [{"insertText": {"location": {"index": 1}, "text": text}}]},
    ).execute()

    return {
        "document_id": doc_id,
        "url": f"https://docs.google.com/document/d/{doc_id}/edit",
    }


def send_or_draft_email(to: str, subject: str, body: str, as_draft: bool) -> dict:
    """Sends an email, or saves it as a Gmail draft. Returns the Gmail API result."""
    gmail = _gmail_service()
    message = MIMEText(body, "plain", "utf-8")
    message["to"] = to
    message["subject"] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

    if as_draft:
        result = gmail.users().drafts().create(userId="me", body={"message": {"raw": raw}}).execute()
        return {"status": "draft", "draft_id": result.get("id")}
    else:
        result = gmail.users().messages().send(userId="me", body={"raw": raw}).execute()
        return {"status": "sent", "message_id": result.get("id")}
