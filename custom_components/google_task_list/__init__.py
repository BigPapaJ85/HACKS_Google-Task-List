# __init__.py
"""Google Task List integration for Home Assistant."""

import logging  # noqa: I001

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.typing import ConfigType

from .const import ATTR_USER_ID, DOMAIN
from .coordinator import TaskDataCoordinator


_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["button"]

# Define constants for service names and attributes
SERVICE_REFRESH_TASKS = "refresh_tasks"
SERVICE_COMPLETE_TASK = "set_task_completed"
SERVICE_INCOMPLETE_TASK = "set_pending_task_to_incomplete"
ATTR_TASK_NAME = "task_name"
device_class = "update"


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Google Task List integration."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Google Task List from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    coordinator = TaskDataCoordinator(
        hass=hass,
        entry=entry,  # Pass the full entry
    )

    # Fetch initial data so we have it when platforms are set up
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
    }

    # Forward the setup to the button platform
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # --- REGISTER THE SERVICES ---

    # Handler for the refresh service (defined locally)
    async def handle_refresh_tasks(call: ServiceCall):
        """Handle the service call to refresh tasks."""
        _LOGGER.info("Task refresh requested by service call")
        await coordinator.async_request_refresh()

    # Define service handlers as coroutines with access to the coordinator
    # This is the correct pattern to avoid the 'RuntimeWarning'
    # by explicitly awaiting the helper functions.
    async def handle_complete_service_call(call: ServiceCall):
        """Helper to properly await the handler function."""
        await handle_complete_task(call, coordinator)

    async def handle_incomplete_service_call(call: ServiceCall):
        """Helper to properly await the handler function."""
        await handle_incomplete_pending_task(call, coordinator)

    hass.services.async_register(DOMAIN, SERVICE_REFRESH_TASKS, handle_refresh_tasks)

    # Register the 'complete task' service with the new helper coroutine
    hass.services.async_register(
        DOMAIN,
        SERVICE_COMPLETE_TASK,
        handle_complete_service_call,
        schema=vol.Schema(
            {
                vol.Required(ATTR_TASK_NAME): str,
                vol.Optional(ATTR_USER_ID): str,
            }
        ),
    )

    # Register the 'incomplete task' service with the new helper coroutine
    hass.services.async_register(
        DOMAIN,
        SERVICE_INCOMPLETE_TASK,
        handle_incomplete_service_call,
        schema=vol.Schema(
            {
                vol.Required(ATTR_TASK_NAME): str,
            }
        ),
    )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # Unload platforms
    unload_ok = await hass.config_entries.async_forward_entry_unload(
        entry, PLATFORMS[0]
    )

    if unload_ok:
        # Unregister all services
        hass.services.async_remove(DOMAIN, SERVICE_REFRESH_TASKS)
        hass.services.async_remove(DOMAIN, SERVICE_COMPLETE_TASK)
        hass.services.async_remove(DOMAIN, SERVICE_INCOMPLETE_TASK)

        # Stop the coordinator's scheduled refresh
        coordinator: TaskDataCoordinator = hass.data[DOMAIN][entry.entry_id][
            "coordinator"
        ]
        coordinator.stop_refresh = True

        # Remove data for this entry
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)


# --- Service Handler Functions ---
# These functions MUST be defined at the top level of the file
# so they are in the correct scope when services are registered.


async def handle_complete_task(call: ServiceCall, coordinator: TaskDataCoordinator):
    """Handle the service call to mark a task as completed."""

    task_name = call.data.get(ATTR_TASK_NAME)

    context_user_id = call.context.user_id
    user = (
        await call.hass.auth.async_get_user(context_user_id)
        if context_user_id
        else None
    )

    user_name = (
        user.name
        if user and user.name
        else user.username
        if user and user.username
        else call.data.get("user_id", "unknown")
    )

    _LOGGER.info(
        f"Service call: Marking task '{task_name}' as completed by user {user_name}"
    )
    await coordinator.async_complete_task(task_name, user_name)


async def handle_incomplete_pending_task(
    call: ServiceCall, coordinator: TaskDataCoordinator
):
    """Handle the service call to mark a task as incomplete."""
    task_name = call.data.get(ATTR_TASK_NAME)
    _LOGGER.info(f"Service call: Marking task '{task_name}' as incomplete.")
    await coordinator.async_incomplete_pending_task(task_name)
