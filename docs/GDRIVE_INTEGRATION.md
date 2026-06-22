# Google Drive CSV Integration

## Overview

Each buyer persona (and the Old Clients module) has a dedicated CSV file on Google Drive. When the multi-agent workflow finds new leads, they are automatically appended to the corresponding CSV. If a CSV doesn't exist yet, it is created automatically with headers.

This allows you to:
- Maintain per-persona lead lists outside the SQLite database
- Download CSVs directly from the UI for external analysis or import into CRM tools
- Keep a persistent, human-readable backup of all discovered leads

## Per-Persona CSV Files

| Persona Key | Drive Filename | Product |
|---|---|---|
| `evinra_events` | `evinra_events_leads.csv` | Evinra |
| `travelorhub_transport` | `travelorhub_transport_leads.csv` | TravelorHub |
| `custom_dev_smb` | `custom_dev_smb_leads.csv` | Custom Development |
| `custom_dev_founders` | `custom_dev_founders_leads.csv` | Custom Dev / MVP Build |
| `old_client` | `old_client_leads.csv` | (varies by imported record) |
| `general` | `general_leads.csv` | Generic niche leads |

## CSV Column Structure

```
name,email,phone,event_name,event_url,event_start_date,event_end_date,
persona_type,target_product,source_type,notes,status,created_at
```

| Column | Description |
|--------|-------------|
| `name` | Contact name or organization |
| `email` | Email address |
| `phone` | Phone number |
| `event_name` | Event name |
| `event_url` | Source URL |
| `event_start_date` | Event start date (YYYY-MM-DD) |
| `event_end_date` | Event end date (YYYY-MM-DD) |
| `persona_type` | Persona key (e.g. `evinra_events`, `old_client`) |
| `target_product` | Product (e.g. `Evinra`, `TravelorHub`) |
| `source_type` | Origin: `web_search`, `csv_import`, or `manual` |
| `notes` | Additional notes |
| `status` | Lead status: `new`, `marketed`, `responded`, `invalid` |
| `created_at` | Timestamp when the row was added |

## How It Works

### Workflow Integration (`graph.py`)

A new node `gdrive_sync_node` runs after `deduplicator` and `notifier`:

```
brainstormer → summarizer → deduplicator → notifier → gdrive_sync → END
brainstormer → searcher → scraper → deduplicator ↗
brainstormer → agentic_researcher → deduplicator ↗
```

The node reads the `saved_leads` accumulator from the graph state (populated by `deduplicator_node` with full lead data including `persona_type`) and calls `sync_leads_to_drive()` to group leads by persona and append each group to its Drive CSV. Duplicates are detected by email and phone within each CSV.

### Old Clients & Manual Entry (`app.py`)

When you import a CSV or add a manual contact (Tab 3), the imported/entered leads are also synced to the `old_client_leads.csv` on Drive:

- **Manual contact:** Synced immediately after successful creation
- **CSV import:** All newly inserted records are fetched and synced in batch

### Deduplication Strategy

When appending to a Drive CSV, existing rows are read and deduplicated by:
1. **Email** (case-insensitive)
2. **Phone** (exact match; only checked if no email)

If a lead's email already exists in the CSV, it is skipped. If it has no email but a phone that already exists, it is also skipped. This prevents duplicate entries across multiple workflow runs.

## UI Download Feature

### Tab 2 — ProDev Personas

Four download buttons below the persona trigger section, one per persona:
- **📥 Evinra Events** — downloads `evinra_events_leads.csv`
- **📥 TravelorHub** — downloads `travelorhub_transport_leads.csv`
- **📥 Custom Dev SMB** — downloads `custom_dev_smb_leads.csv`
- **📥 Custom Dev Founders** — downloads `custom_dev_founders_leads.csv`

All buttons share a single `gr.File` output component. Clicking any button will either:
- Download the existing CSV from Drive, or
- Generate a local CSV with headers only if no Drive CSV exists yet

### Tab 3 — Old Clients Manager

A download button at the bottom of the tab:
- **📥 Descargar CSV de Clientes Antiguos** — downloads `old_client_leads.csv`

## Setup Instructions

### 1. Google Cloud Platform Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or select existing)
3. Navigate to **APIs & Services → Library**
4. Search for **Google Drive API** and click **Enable**
5. Go to **APIs & Services → Credentials**
6. Click **Create Credentials → Service Account**
7. Name it (e.g., `prodev-gdrive-sync`) and click **Create and Continue**
8. Skip the role/permissions steps (click **Done**)
9. Click on the newly created service account
10. Go to the **Keys** tab → **Add Key** → **Create New Key** → **JSON**
11. The JSON key file will download — store it securely (this is your credential file)

### 2. Google Drive Folder Setup

1. Open [Google Drive](https://drive.google.com/)
2. Create a new folder (e.g., `ProDev Leads`)
3. Note the service account email from step 1 (found in the JSON key as `client_email` or in the Cloud Console)
4. Share the folder with that email address with **Editor** permissions
5. Open the folder in your browser and copy the **Folder ID** from the URL:
   ```
   https://drive.google.com/drive/folders/1ABCxyz1234567890
   ```
   The Folder ID is: `1ABCxyz1234567890`

### 3. Environment Configuration

Add to your `.env` file:

```env
# Google Drive (Service Account for persona CSV sync)
GDRIVE_CREDENTIALS_PATH=C:\path\to\your\service-account-key.json
GDRIVE_FOLDER_ID=1ABCxyz1234567890
```

### 4. Install Dependencies

```powershell
uv sync
```

## Architecture

### Module: `gdrive_manager.py`

| Function | Purpose |
|---|---|
| `_get_service()` | Authenticates with Drive API using service account credentials |
| `get_or_create_csv(persona_key)` | Finds existing CSV by name in the configured folder, or creates one with headers |
| `append_leads_to_csv(file_id, leads)` | Downloads current CSV, parses existing rows, deduplicates, appends new rows, uploads |
| `download_csv_to_temp(persona_key)` | Exports the CSV from Drive to a local temporary file for download |
| `sync_leads_to_drive(leads)` | Groups a list of lead dicts by `persona_type` and syncs each group via `get_or_create_csv` + `append_leads_to_csv` |

### Data Flow

```
Workflow finds leads → deduplicator saves to SQLite + populates saved_leads
  → notifier sends alerts
  → gdrive_sync_node calls sync_leads_to_drive(saved_leads)
    → groups by persona_type
    → for each group: get_or_create_csv() → append_leads_to_csv()
```

## Error Handling

- If `GDRIVE_CREDENTIALS_PATH` is not set or the file doesn't exist → Drive sync is skipped with a warning log
- If `GDRIVE_FOLDER_ID` is not configured → sync is skipped with an error log
- If the Google Drive API call fails (network, permissions, etc.) → the error is logged and the workflow continues without crashing
- If Google API Python dependencies are not installed → `gdrive_sync_node` catches `ImportError` and skips sync gracefully

## Troubleshooting

**"GDrive credentials not found"** → Check that `GDRIVE_CREDENTIALS_PATH` in `.env` points to the actual JSON key file.

**"GDRIVE_FOLDER_ID not configured"** → Add the folder ID to `.env`. It's the string after `/folders/` in the Drive URL.

**403 Permission Denied** → Make sure the folder on Google Drive is shared with the service account email (the `client_email` from the JSON key) with **Editor** access.

**No CSVs appearing in Drive** → Run the workflow at least once with a persona selected. The CSVs are created lazily on first sync.

**Download returns empty CSV** → No leads have been synced yet for that persona, or the file was just created with headers only.