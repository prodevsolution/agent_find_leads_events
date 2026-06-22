"""
gdrive_manager.py
-----------------
Google Drive integration for persona-specific CSV lead storage.
Uses OAuth 2.0 with a stored refresh token so files are owned by your
real Google account (which has Drive storage quota).
"""

import os
import io
import csv
import json
import logging
import tempfile
from datetime import datetime

import config

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive"]

PERSONA_CSV_FILES = {
    "evinra_events": "evinra_events_leads.csv",
    "travelorhub_transport": "travelorhub_transport_leads.csv",
    "custom_dev_smb": "custom_dev_smb_leads.csv",
    "custom_dev_founders": "custom_dev_founders_leads.csv",
    "old_client": "old_client_leads.csv",
    "general": "general_leads.csv",
}

CSV_HEADERS = [
    "name", "email", "phone", "event_name", "event_url",
    "event_start_date", "event_end_date",
    "persona_type", "target_product", "source_type",
    "notes", "status", "created_at",
]

# ── Helpers ──────────────────────────────────────────────────────────────────

def _load_token() -> dict | None:
    path = config.GDRIVE_TOKEN_PATH
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Failed to load token from {path}: {e}")
        return None


def _save_token(token: dict):
    path = config.GDRIVE_TOKEN_PATH
    if not path:
        logger.error("GDRIVE_TOKEN_PATH not configured, cannot save token")
        return
    with open(path, "w", encoding="utf-8") as f:
        json.dump(token, f, indent=2)
    logger.info(f"Token saved to {path}")


def _get_service():
    """Build and return an authenticated Drive v3 service via OAuth 2.0."""
    if not all([config.GDRIVE_CLIENT_ID, config.GDRIVE_CLIENT_SECRET, config.GDRIVE_TOKEN_PATH]):
        logger.warning("Google Drive OAuth 2.0 not fully configured")
        return None

    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    token = _load_token()
    if not token:
        logger.warning("No OAuth token found — run scripts/setup_gdrive_oauth.py first")
        return None

    creds = Credentials.from_authorized_user_info(token, SCOPES)

    # Refresh if expired
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save_token(json.loads(creds.to_json()))
        except Exception as e:
            logger.error(f"Failed to refresh OAuth token: {e}")
            return None

    return build("drive", "v3", credentials=creds)


# ── Core operations ──────────────────────────────────────────────────────────

def get_or_create_csv(persona_key: str) -> tuple[str | None, bool]:
    """Find existing CSV or create a new one. Returns (file_id, is_new)."""
    service = _get_service()
    if not service:
        return None, False

    filename = PERSONA_CSV_FILES.get(persona_key, f"{persona_key}_leads.csv")
    folder_id = config.GDRIVE_FOLDER_ID

    if not folder_id:
        logger.error("GDRIVE_FOLDER_ID not configured")
        return None, False

    query = f"name='{filename}' and '{folder_id}' in parents and trashed=false"
    results = service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get("files", [])

    if files:
        return files[0]["id"], False

    from googleapiclient.http import MediaIoBaseUpload
    file_metadata = {"name": filename, "parents": [folder_id], "mimeType": "text/csv"}
    header_row = ",".join(CSV_HEADERS) + "\n"
    media = MediaIoBaseUpload(io.BytesIO(header_row.encode()), mimetype="text/csv", resumable=True)
    created = service.files().create(body=file_metadata, media_body=media, fields="id").execute()
    logger.info(f"Created new CSV on Drive: {filename} (id: {created['id']})")
    return created["id"], True


def append_leads_to_csv(file_id: str, leads: list[dict]) -> int:
    """Append new leads to an existing CSV. Returns count of rows appended."""
    service = _get_service()
    if not service:
        return 0

    from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

    try:
        request = service.files().get_media(fileId=file_id)
        existing = io.BytesIO()
        downloader = MediaIoBaseDownload(existing, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
    except Exception:
        # Fallback: try export (for Google Sheets native format)
        request = service.files().export_media(fileId=file_id, mimeType="text/csv")
        existing = io.BytesIO()
        downloader = MediaIoBaseDownload(existing, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
    existing.seek(0)

    existing_text = existing.read().decode("utf-8", errors="replace")

    existing_emails: set[str] = set()
    existing_phones: set[str] = set()
    reader = csv.DictReader(io.StringIO(existing_text))
    for row in reader:
        e = (row.get("email") or "").strip().lower()
        p = (row.get("phone") or "").strip()
        if e:
            existing_emails.add(e)
        if p:
            existing_phones.add(p)

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    new_rows: list[dict] = []
    for lead in leads:
        email = (lead.get("email") or "").strip().lower()
        phone = (lead.get("phone") or "").strip()
        if email and email in existing_emails:
            continue
        if phone and phone in existing_phones:
            continue
        if email:
            existing_emails.add(email)
        if phone:
            existing_phones.add(phone)

        s_date = lead.get("event_start_date")
        e_date = lead.get("event_end_date")
        if hasattr(s_date, "strftime"):
            s_date = s_date.strftime("%Y-%m-%d")
        if hasattr(e_date, "strftime"):
            e_date = e_date.strftime("%Y-%m-%d")

        new_rows.append({
            "name": lead.get("name") or "",
            "email": lead.get("email") or "",
            "phone": lead.get("phone") or "",
            "event_name": lead.get("event_name") or "",
            "event_url": lead.get("event_url") or "",
            "event_start_date": s_date or "",
            "event_end_date": e_date or "",
            "persona_type": lead.get("persona_type") or "",
            "target_product": lead.get("target_product") or "",
            "source_type": lead.get("source_type") or "",
            "notes": lead.get("notes") or "",
            "status": lead.get("status") or "new",
            "created_at": now_str,
        })

    if not new_rows:
        return 0

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=CSV_HEADERS)
    lines = existing_text.strip().splitlines()
    if len(lines) <= 1:
        writer.writeheader()
    else:
        output.write(existing_text.rstrip("\n") + "\n")
    writer.writerows(new_rows)

    media = MediaIoBaseUpload(io.BytesIO(output.getvalue().encode("utf-8")), mimetype="text/csv", resumable=True)
    service.files().update(fileId=file_id, media_body=media).execute()
    logger.info(f"Appended {len(new_rows)} leads to Drive CSV (file_id: {file_id})")
    return len(new_rows)


# ── Local fallback ────────────────────────────────────────────────────────────

def _write_leads_to_csv(path: str, persona_key: str):
    from database import repository as _repo

    if persona_key in ("general", "old_client"):
        leads = _repo.get_leads_by_persona(persona_key)
    else:
        leads = _repo.get_recent_leads(None, persona_type=persona_key, target_product="All")

    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_HEADERS)
        for lead in leads:
            s_date = lead.event_start_date
            e_date = lead.event_end_date
            if hasattr(s_date, "strftime"):
                s_date = s_date.strftime("%Y-%m-%d")
            if hasattr(e_date, "strftime"):
                e_date = e_date.strftime("%Y-%m-%d")
            writer.writerow([
                lead.name or "",
                lead.email or "",
                lead.phone or "",
                lead.event_name or "",
                lead.event_url or "",
                s_date or "",
                e_date or "",
                lead.persona_type or "",
                lead.target_product or "",
                lead.source_type or "",
                lead.notes or "",
                lead.status or "new",
                lead.created_at.strftime("%Y-%m-%d %H:%M:%S") if lead.created_at else "",
            ])


# ── Local CSV sync ────────────────────────────────────────────────────────────

def _local_csv_path(persona_key: str) -> str:
    """Return the local filesystem path for a persona's CSV."""
    filename = PERSONA_CSV_FILES.get(persona_key, f"{persona_key}_leads.csv")
    storage_dir = os.path.abspath(config.CSV_STORAGE_DIR)
    os.makedirs(storage_dir, exist_ok=True)
    return os.path.join(storage_dir, filename)


def _sync_leads_local(persona_key: str, leads: list[dict]) -> int:
    """Append new leads to the local CSV for a persona. Returns count of new rows."""
    path = _local_csv_path(persona_key)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    existing_emails: set[str] = set()
    existing_phones: set[str] = set()

    if os.path.exists(path):
        with open(path, encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                e = (row.get("email") or "").strip().lower()
                p = (row.get("phone") or "").strip()
                if e:
                    existing_emails.add(e)
                if p:
                    existing_phones.add(p)

    new_rows: list[dict] = []
    for lead in leads:
        email = (lead.get("email") or "").strip().lower()
        phone = (lead.get("phone") or "").strip()
        if email and email in existing_emails:
            continue
        if phone and phone in existing_phones:
            continue
        if email:
            existing_emails.add(email)
        if phone:
            existing_phones.add(phone)

        s_date = lead.get("event_start_date")
        e_date = lead.get("event_end_date")
        if hasattr(s_date, "strftime"):
            s_date = s_date.strftime("%Y-%m-%d")
        if hasattr(e_date, "strftime"):
            e_date = e_date.strftime("%Y-%m-%d")

        new_rows.append({
            "name": lead.get("name") or "",
            "email": lead.get("email") or "",
            "phone": lead.get("phone") or "",
            "event_name": lead.get("event_name") or "",
            "event_url": lead.get("event_url") or "",
            "event_start_date": s_date or "",
            "event_end_date": e_date or "",
            "persona_type": lead.get("persona_type") or "",
            "target_product": lead.get("target_product") or "",
            "source_type": lead.get("source_type") or "",
            "notes": lead.get("notes") or "",
            "status": lead.get("status") or "new",
            "created_at": now_str,
        })

    if not new_rows:
        return 0

    write_header = not os.path.exists(path) or os.path.getsize(path) == 0
    with open(path, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        if write_header:
            writer.writeheader()
        writer.writerows(new_rows)

    logger.info(f"Appended {len(new_rows)} leads to local CSV: {path}")
    return len(new_rows)


# ── Public API ────────────────────────────────────────────────────────────────

def download_csv_to_temp(persona_key: str) -> str | None:
    """
    Download a persona's CSV. Tries the local CSV first; then Google Drive;
    finally generates from the local SQLite database.
    The output file is named after the persona
    (e.g. evinra_events_leads.csv) so Gradio serves it with the correct name.
    """
    filename = PERSONA_CSV_FILES.get(persona_key, f"{persona_key}_leads.csv")
    out_path = os.path.join(tempfile.gettempdir(), filename)

    # 1) Try local CSV
    local_path = _local_csv_path(persona_key)
    if os.path.exists(local_path):
        try:
            import shutil
            shutil.copy2(local_path, out_path)
            logger.info(f"Copied local CSV for {persona_key} to {out_path}")
            return out_path
        except Exception as e:
            logger.warning(f"Failed to copy local CSV: {e}")

    # 2) Try Google Drive
    service = _get_service()
    if service and config.GDRIVE_FOLDER_ID:
        try:
            query = f"name='{filename}' and '{config.GDRIVE_FOLDER_ID}' in parents and trashed=false"
            results = service.files().list(q=query, fields="files(id, name)").execute()
            files = results.get("files", [])
            if files:
                from googleapiclient.http import MediaIoBaseDownload
                try:
                    request = service.files().get_media(fileId=files[0]["id"])
                except Exception:
                    request = service.files().export_media(fileId=files[0]["id"], mimeType="text/csv")
                content = io.BytesIO()
                downloader = MediaIoBaseDownload(content, request)
                done = False
                while not done:
                    _, done = downloader.next_chunk()
                content.seek(0)
                with open(out_path, "wb") as f:
                    f.write(content.read())
                logger.info(f"Downloaded {filename} from Google Drive")
                return out_path
        except Exception as e:
            logger.warning(f"GDrive download failed for {filename}, falling back to DB: {e}")

    # 3) Fallback: generate from SQLite
    try:
        _write_leads_to_csv(out_path, persona_key)
        logger.info(f"Generated {filename} from local database")
        return out_path
    except Exception as e:
        logger.error(f"Failed to generate CSV from DB for {persona_key}: {e}")
        return None


def sync_leads_to_drive(leads: list[dict]) -> int:
    """
    Group leads by persona_type and sync each group.
    Always saves to local CSVs; also attempts Google Drive sync if configured.
    Returns total appended.
    """
    if not leads:
        return 0

    by_persona: dict[str, list[dict]] = {}
    for lead in leads:
        pt = lead.get("persona_type") or "general"
        if pt not in PERSONA_CSV_FILES:
            continue
        by_persona.setdefault(pt, []).append(lead)

    total = 0
    for persona, group in by_persona.items():
        # Always sync locally
        total += _sync_leads_local(persona, group)

        # Also try Google Drive if available
        try:
            file_id, _ = get_or_create_csv(persona)
            if file_id:
                total += append_leads_to_csv(file_id, group)
        except Exception as e:
            logger.warning(f"GDrive sync skipped for persona '{persona}': {e}")

    return total
