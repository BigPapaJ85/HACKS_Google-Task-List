# config_flow.py

from homeassistant import config_entries
import voluptuous as vol
from .const import DOMAIN


class GoogleTaskListConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Google Task List."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        if user_input is not None:
            # Use the sheet name as the unique ID to prevent duplicates
            await self.async_set_unique_id(user_input["sheet_name"])
            self._abort_if_unique_id_configured()

            # Create the config entry
            return self.async_create_entry(
                title=user_input["name"],  # Use the friendly name for the title
                data=user_input,  # Store all form data
            )

        # Show the form to the user if no input is provided
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("name", default="Google Task List"): str,
                    vol.Required("sheet_name", default="Harvey_Task_Tracker"): str,
                    vol.Required("task_worksheet", default="Tasks"): str,
                    vol.Required("log_worksheet", default="Log"): str,
                    vol.Required(
                        "creds_path", default="config/google_sheets_creds.json"
                    ): str,
                    vol.Optional("category", default="PT Tasks"): str,
                    vol.Optional("entity_prefix", default="H_Chore"): str,
                }
            ),
        )
