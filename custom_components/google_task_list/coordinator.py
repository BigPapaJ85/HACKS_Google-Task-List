# coordinator.py

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.core import HomeAssistant
from datetime import datetime, timedelta, time, timezone
from zoneinfo import ZoneInfo
from croniter import croniter
from homeassistant.config_entries import ConfigEntry
import logging

# Changed import name to match class name
from .google_sheet_clients import GoogleSheetsClient


_LOGGER = logging.getLogger("custom_components.google_task_list")
CENTRAL = ZoneInfo("America/Chicago")


def cron_run_required(
    cron_expression: str | None, last_completed_str: str | None, now: datetime
) -> bool:
    """
    Checks if a task is active due based on its cron expression and last completed timestamp.
    """
    if not cron_expression:
        # One-time task. It's active if it has never been completed.
        return last_completed_str is None

    try:
        # Define a start point for the cron iteration
        # If the task was completed, start from that time.
        # Otherwise, start from a long time ago to find the first run.
        start_time = (
            datetime.fromisoformat(last_completed_str).astimezone(now.tzinfo)
            if last_completed_str
            else datetime(1, 1, 1, tzinfo=now.tzinfo)
        )

        # Get the next scheduled run time after the start time
        iter = croniter(cron_expression, start_time)
        next_run = iter.get_next(datetime)

        # The task is active if its next scheduled run is on or before now.
        return next_run <= now

    except Exception as e:
        _LOGGER.warning(f"Invalid cron expression '{cron_expression}': {e}")
        return False


class TaskDataCoordinator(DataUpdateCoordinator):
    """Coordinator to manage and schedule recurring Google Task List updates."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):  # Changed signature
        super().__init__(
            hass, _LOGGER, name="google_task_list_data", update_interval=None
        )
        self.config_entry = entry

        # Get config from entry data
        creds_path = entry.data["creds_path"]
        sheet_name = entry.data["sheet_name"]
        task_worksheet = entry.data["task_worksheet"]
        log_worksheet = entry.data["log_worksheet"]

        # Fixed client name
        self.client = GoogleSheetsClient(
            creds_path, sheet_name, task_worksheet, log_worksheet
        )
        self.stop_refresh = False

        # Start the background refresh loop
        self._schedule_five_minutely_refresh()

    def _schedule_five_minutely_refresh(self):
        """Schedule refresh every 5 minutes aligned to clock time."""
        now = datetime.now(timezone.utc)
        next_run = (now + timedelta(minutes=5)).replace(second=0, microsecond=0)
        minute = next_run.minute - (next_run.minute % 5)
        next_run = next_run.replace(minute=minute)

        _LOGGER.debug(f"Next 5-min refresh scheduled at {next_run.isoformat()}")

        async_track_point_in_utc_time(
            self.hass, self._handle_scheduled_refresh, next_run
        )

    async def _handle_scheduled_refresh(self, now):
        if self.stop_refresh:
            _LOGGER.info("Scheduled refresh skipped due to unload")
            return
        _LOGGER.info("Running scheduled 5-minute task refresh")
        await self.async_refresh()
        self._schedule_five_minutely_refresh()

    async def _async_update_data(self):
        """Fetch updated task list and re-evaluate state only when necessary."""
        try:
            # Get the previous data to check for existing tasks and their states.
            previous_data_by_name = (
                {task.get("task"): task for task in self.data} if self.data else {}
            )
            await self.hass.async_add_executor_job(self.client.load_sheet)
            _LOGGER.debug("Fetching tasks from Google Sheets")

            raw_tasks = await self.hass.async_add_executor_job(self.client.get_tasks)

            updated_tasks = []
            for task in raw_tasks:
                task_name = task.get("task", "Unnamed")
                previous_task = previous_data_by_name.get(task_name, {})
                # Default to previously known values if available
                task["state"] = previous_task.get("state", "not_completed")
                task["visible"] = previous_task.get("visible", True)
                last_completed = task.get("last_completed", "")
                cron = task.get("cron_frequency")

                if (
                    task["state"] == "completed"
                    and cron is not None
                    and cron_run_required(cron, last_completed, datetime.now(CENTRAL))
                ):
                    task["visible"] = True
                    task["state"] = "not_completed"
                    _LOGGER.debug(
                        "Task '%s' was updated to due based on cron '%s'.",
                        task_name,
                        cron,
                    )

                updated_tasks.append(task)

            return updated_tasks

        except Exception as err:
            _LOGGER.warning("Failed to update tasks: %s", err)
            raise UpdateFailed(f"Error fetching tasks: {err}") from err

    async def async_complete_task(self, task_name: str, user_id: str = "unknown"):
        """Mark a task as completed and update the sheet."""
        _LOGGER.info(f"Completing task '{task_name}' by user '{user_id}'...")

        try:
            updated_tasks = list(self.data)
            found_task = None

            for task in updated_tasks:
                if task.get("task") == task_name:
                    found_task = task
                    break

            if not found_task:
                _LOGGER.warning(f"Task '{task_name}' not found.")
                return

            # Set new task values
            found_task["state"] = "completed"
            found_task["visible"] = False
            now = datetime.now(CENTRAL).isoformat(timespec="seconds")
            found_task["last_completed"] = now

            # Update HA state
            self.async_set_updated_data(updated_tasks)

            # Google Sheet updates
            await self.hass.async_add_executor_job(
                self.client.update_task_status, task_name, now
            )

            await self.hass.async_add_executor_job(
                self.client.log_action, task_name, "completed", user_id
            )

            _LOGGER.info(f"Task '{task_name}' completed by '{user_id}'.")

        except Exception as err:
            _LOGGER.error(f"Error completing task '{task_name}': {err}")

    async def async_incomplete_pending_task(self, task_name: str):
        """Return a pending task to a not_completed state."""
        _LOGGER.info(f"Returning task '{task_name}' from pending to not_completed.")

        try:
            # Create a mutable copy of the current data.
            # This is important so you don't modify the data while it's being used.
            updated_tasks = list(self.data)
            found_task = None

            # Find the task in the list
            for task in updated_tasks:
                if task.get("task") == task_name:
                    found_task = task
                    break

            if found_task:
                # Modify the task's state directly.
                found_task["state"] = "not_completed"
                found_task["visible"] = True
                _LOGGER.debug(f"Task '{task_name}' status updated to 'not_completed'.")

                # Update the coordinator's data and notify Home Assistant.
                self.async_set_updated_data(updated_tasks)
            else:
                _LOGGER.warning(f"Task '{task_name}' not found in coordinator data.")

        except Exception as err:
            _LOGGER.error(f"Failed to set task '{task_name}' as incomplete: {err}")
            # The update failed, so we should log the error and possibly raise an exception.
