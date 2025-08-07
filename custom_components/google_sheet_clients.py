# google_sheets_client.py

import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import logging

_LOGGER = logging.getLogger(__name__)


class GoogleSheetsClient:
    def __init__(
        self,
        path_to_creds: str,
        sheet_name: str,
        task_worksheet: str,
        log_worksheet: str,
    ):
        SCOPES = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        self.creds = Credentials.from_service_account_file(path_to_creds, scopes=SCOPES)
        self.client = gspread.authorize(self.creds)
        self.sheet_name = sheet_name
        self.task_worksheet = task_worksheet
        self.log_worksheet = log_worksheet

        self.sheet = None
        self.task_ws = None
        self.log_ws = None

    def load_sheet(self):
        """Load the Google Sheet and worksheets — runs in executor thread."""
        self.sheet = self.client.open(self.sheet_name)
        self.task_ws = self.sheet.worksheet(self.task_worksheet)
        self.log_ws = self.sheet.worksheet(self.log_worksheet)

    def get_tasks(self) -> list[dict]:
        """Load task rows from the task worksheet into dictionaries with normalized lowercase keys."""
        tasks = self.task_ws.get_all_records()
        normalized = []

        for task in tasks:
            cleaned_task = {}

            # First, lowercase all keys
            task_lower = {
                k.lower(): v.strip() if isinstance(v, str) else v
                for k, v in task.items()
            }

            # Normalize known fields
            cleaned_task["task"] = task_lower.get("task", "")
            cleaned_task["assigned_to"] = task_lower.get("assigned_to", "unknown")
            cleaned_task["cron_frequency"] = task_lower.get("cron_frequency") or None
            cleaned_task["last_completed"] = task_lower.get("last_completed", "")
            cleaned_task["visible"] = task_lower.get("visible", True)

            # Add any remaining fields
            for k, v in task_lower.items():
                if k not in cleaned_task:
                    cleaned_task[k] = v
            normalized.append(cleaned_task)

        if not normalized:
            raise ValueError("No tasks found in sheet")

        required_fields = {"task", "cron_frequency", "last_completed"}
        found_fields = set(normalized[0].keys())

        missing_fields = required_fields - found_fields
        if missing_fields:
            raise ValueError(f"Missing required column(s): {', '.join(missing_fields)}")

        return normalized

    def update_task_status(self, task_name: str, last_completed_str: str):
        """
        Finds a task by name and updates its 'Last Completed' column.
        Args:
            task_name (str): The name of the task to update.
            last_completed_str (str): The timestamp string to update 'Last Completed' with.
            Use an empty string to clear the value.
        """

        _LOGGER.debug(f"Updating status for task '{task_name}'...")
        cell = self.task_ws.find(task_name)
        if not cell:
            _LOGGER.warning(f"Could not find task '{task_name}' to update.")
            return

        row_index = cell.row
        header = self.task_ws.row_values(1)
        header_lower = [h.strip().lower() for h in header]

        try:
            last_completed_col_index = header_lower.index("last_completed") + 1
        except ValueError as e:
            _LOGGER.error(f"Could not find column header: {e}")
            raise Exception(
                f"Could not find required column 'Last Completed' in sheet header."
            )

        try:
            self.task_ws.update_cell(
                row_index, last_completed_col_index, last_completed_str
            )
        except Exception as e:
            _LOGGER.error(f"Google API error while updating task '{task_name}': {e}")
            raise

        _LOGGER.debug(
            f"Updated task '{task_name}' with Last Completed: '{last_completed_str}'"
        )

    def log_action(self, task_name: str, action: str, user: str = "unknown"):
        """Append a log row with timestamp, task, user, and action (Central Time)."""
        _LOGGER.debug(f"Logging action '{action}' for task '{task_name}'...")
        timestamp = datetime.now().isoformat(timespec="seconds")
        row = [timestamp, task_name, user, action]

        try:
            self.log_ws.append_row(row, value_input_option="RAW")

        except Exception as e:
            _LOGGER.error(f"Google API error while logging '{task_name}': {e}")
            raise
