"""Google Sheets TODO manager — syncs TODOs to a Google Sheet with feedback loop support."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from .config import Config
from .db import Database

logger = logging.getLogger(__name__)

# Column layout matching the tech spec
SHEET_HEADERS = [
    "ID", "Manual Status", "Delegated To", "System Status", "Urgency",
    "Title", "Context", "Source Message", "Source Author", "Source Channel",
    "Thread Link", "Owner", "Due Date", "Created", "Last Updated",
    "LLM Correct?", "Correction Notes", "Notes",
]

HEADER_ROW = 1
DATA_START_ROW = 2


def _get_gspread_client(credentials_path: str):
    """Create an authenticated gspread client."""
    import gspread
    from google.oauth2.service_account import Credentials

    creds_path = Path(credentials_path).expanduser()
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    credentials = Credentials.from_service_account_file(str(creds_path), scopes=scopes)
    return gspread.authorize(credentials)


class SheetsManager:
    """Manages the Google Sheet TODO list with dual-status support."""

    def __init__(self, config: Config, db: Database):
        self.config = config
        self.db = db
        self._gc = None
        self._sheet = None

    @property
    def gc(self):
        if self._gc is None:
            self._gc = _get_gspread_client(self.config.todo.google_credentials_path)
        return self._gc

    @property
    def sheet(self):
        if self._sheet is None:
            spreadsheet = self.gc.open_by_key(self.config.todo.sheet_id)
            try:
                self._sheet = spreadsheet.worksheet(self.config.todo.sheet_name)
            except Exception:
                # Create the worksheet if it doesn't exist
                self._sheet = spreadsheet.add_worksheet(
                    title=self.config.todo.sheet_name,
                    rows=500,
                    cols=len(SHEET_HEADERS),
                )
                self._initialize_sheet()
        return self._sheet

    def _initialize_sheet(self) -> None:
        """Set up headers, formatting, and data validation on a new sheet."""
        # Write headers
        self.sheet.update(f"A1:{chr(64 + len(SHEET_HEADERS))}1", [SHEET_HEADERS])

        # Bold + freeze header row
        self.sheet.format("A1:R1", {
            "textFormat": {"bold": True},
            "backgroundColor": {"red": 0.106, "green": 0.227, "blue": 0.361},
            "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
        })
        self.sheet.freeze(rows=1)

        logger.info("Sheet initialized with headers and formatting.")

    def sync_todos(self) -> dict[str, int]:
        """Sync TODOs from local DB to Google Sheet.

        Respects the dual-status design:
        - Only writes to System Status, never Manual Status
        - Skips rows where Manual Status is non-blank
        - Deduplicates by TODO ID

        Returns counts of rows created and updated.
        """
        stats = {"created": 0, "updated": 0, "skipped": 0}
        local_todos = self.db.get_all_todos()

        if not local_todos:
            return stats

        # Get existing sheet data
        existing_rows = self.sheet.get_all_records()
        existing_ids = {row.get("ID", ""): (i + DATA_START_ROW, row) for i, row in enumerate(existing_rows)}

        for todo in local_todos:
            todo_id = f"TODO-{todo['id']:04d}"

            if todo_id in existing_ids:
                row_num, existing = existing_ids[todo_id]

                # Never overwrite rows with manual status set
                if existing.get("Manual Status", "").strip():
                    stats["skipped"] += 1
                    continue

                # Update system status and other system-managed fields
                self._update_row(row_num, todo)
                stats["updated"] += 1
            else:
                # New TODO — append row
                self._append_row(todo)
                stats["created"] += 1

        logger.info(
            f"Sheet sync: {stats['created']} created, "
            f"{stats['updated']} updated, {stats['skipped']} skipped"
        )
        return stats

    def _append_row(self, todo: dict) -> None:
        """Append a new TODO row to the sheet."""
        row = [
            f"TODO-{todo['id']:04d}",          # ID
            "",                                   # Manual Status (human only)
            "",                                   # Delegated To (human only)
            todo.get("status", "open").title(),   # System Status
            todo.get("urgency", "medium").title(), # Urgency
            todo.get("title", ""),                # Title
            todo.get("context", ""),              # Context
            todo.get("source_message", ""),        # Source Message
            todo.get("source_author", ""),         # Source Author
            todo.get("channel_name", ""),          # Source Channel (from thread)
            todo.get("source_permalink", ""),      # Thread Link
            todo.get("owner", ""),                 # Owner
            todo.get("due_date", ""),              # Due Date
            todo.get("created_at", ""),            # Created
            todo.get("updated_at", ""),            # Last Updated
            "",                                   # LLM Correct? (human only)
            "",                                   # Correction Notes (human only)
            "",                                   # Notes (human only)
        ]
        self.sheet.append_row(row, value_input_option="USER_ENTERED")

    def _update_row(self, row_num: int, todo: dict) -> None:
        """Update system-managed columns in an existing row."""
        # Only update: System Status (D), Last Updated (O)
        updates = {
            f"D{row_num}": todo.get("status", "open").title(),
            f"O{row_num}": todo.get("updated_at", ""),
        }
        for cell, value in updates.items():
            self.sheet.update_acell(cell, value)

    def get_corrections(self, limit: int = 20) -> list[dict]:
        """Read user corrections from the sheet for the feedback loop.

        Returns rows where LLM Correct? == 'No' with correction details.
        """
        all_rows = self.sheet.get_all_records()
        corrections = []

        for row in all_rows:
            if row.get("LLM Correct?", "").strip().lower() == "no":
                corrections.append({
                    "todo_id": row.get("ID", ""),
                    "source_message": row.get("Source Message", ""),
                    "source_channel": row.get("Source Channel", ""),
                    "original_classification": "action_required",  # Was a TODO
                    "correction_notes": row.get("Correction Notes", ""),
                    "title": row.get("Title", ""),
                })

        # Return most recent first, limited
        return corrections[-limit:]

    def get_open_todos_for_digest(self) -> list[dict]:
        """Get all effectively open TODOs for digest/email display.

        Applies the dual-status resolution logic:
        Manual Status takes precedence over System Status.
        """
        all_rows = self.sheet.get_all_records()
        open_todos = []

        for row in all_rows:
            manual = row.get("Manual Status", "").strip()
            system = row.get("System Status", "").strip()

            # Compute effective status
            if manual:
                effective = manual
            else:
                effective = system

            # Filter to actionable items
            if effective.lower() in ("open", "delegated", "deferred", "stale"):
                row["effective_status"] = effective
                open_todos.append(row)

        return open_todos


class LocalSheetsManager:
    """Fallback TODO display when Google Sheets is not configured.

    Reads directly from the local SQLite database.
    """

    def __init__(self, config: Config, db: Database):
        self.config = config
        self.db = db

    def sync_todos(self) -> dict[str, int]:
        return {"created": 0, "updated": 0, "skipped": 0, "mode": "local"}

    def get_corrections(self, limit: int = 20) -> list[dict]:
        return []

    def get_open_todos_for_digest(self) -> list[dict]:
        todos = self.db.get_open_todos()
        return [
            {
                "ID": f"TODO-{t['id']:04d}",
                "Title": t.get("title", ""),
                "Urgency": t.get("urgency", "medium"),
                "Due Date": t.get("due_date", ""),
                "Source Channel": "",
                "Thread Link": t.get("source_permalink", ""),
                "effective_status": t.get("status", "open"),
            }
            for t in todos
        ]


def get_sheets_manager(config: Config, db: Database) -> SheetsManager | LocalSheetsManager:
    """Factory that returns SheetsManager if configured, else LocalSheetsManager."""
    if config.todo.sheet_id:
        try:
            return SheetsManager(config, db)
        except Exception as e:
            logger.warning(f"Google Sheets unavailable, using local: {e}")
            return LocalSheetsManager(config, db)
    return LocalSheetsManager(config, db)
