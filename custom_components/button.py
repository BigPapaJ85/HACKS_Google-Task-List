# button.py

from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.core import callback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
import logging
from .coordinator import TaskDataCoordinator
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)
INTEGRATION_NAME = "google_task_list"


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the task buttons from a config entry."""
    coordinator: TaskDataCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    display_name = entry.data.get("name", "Google Task List")
    category = entry.data.get("category", "Unknown")
    entity_prefix = entry.data.get("entity_prefix", "")

    # Wait for the first refresh to have data
    await coordinator.async_config_entry_first_refresh()

    # Create a button for every task in the sheet
    async_add_entities(
        [
            TaskButtonEntity(coordinator, task, display_name, category, entity_prefix)
            for task in coordinator.data
        ]
    )


class TaskButtonEntity(CoordinatorEntity, ButtonEntity):
    """A button entity representing a single task."""

    def __init__(
        self,
        coordinator: TaskDataCoordinator,
        task: dict,
        display_name: str,
        category: str,
        entity_prefix: str = "",
    ):
        """Initialize the button entity."""
        super().__init__(coordinator)
        self.task_id = task[
            "task"
        ]  # Use the task name as its unique ID within the list
        self._display_name = display_name
        self._category = category

        base_slug = self.task_id.lower().replace(" ", "_").replace("-", "_")
        prefix_slug = entity_prefix.lower().replace(" ", "_").replace("-", "_")

        # Construct full entity slug
        full_slug = f"{prefix_slug}_{base_slug}" if prefix_slug else base_slug

        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{full_slug}"
        self._attr_name = f"{entity_prefix} {self.task_id}".strip()
        self.entity_id = f"button.{full_slug}"
        self._attr_name = self.task_id

        _LOGGER.debug(f"Registered button entity: {self.entity_id}")

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.config_entry.entry_id)},
            name=self._display_name,
            manufacturer="Custom",
            entry_type="service",
        )
        # Set initial state from the first data pull
        self._pending_state = False
        self._update_internal_state()

    @property
    def state(self) -> str:
        """Return the state of the button."""
        if self._pending_state:
            return "pending"

        task_data = self._get_task_data()
        return task_data.get("state", "not_completed")

    @property
    def icon(self):
        """Return an icon based on task state."""
        state = self.state
        icon_map = {
            "pending": "mdi:timer-sand",
            "not_completed": "mdi:checkbox-blank-outline",
            "completed": "mdi:check-circle",
        }
        return icon_map.get(state, "mdi:alert")

    @property
    def available(self) -> bool:
        """Always return True so the entity shows up; use state to control appearance."""
        return True

    def _get_task_data(self) -> dict:
        """Find this entity's specific task data from the coordinator's list."""
        for task in self.coordinator.data:
            if task.get("task") == self.task_id:
                return task
        return {}  # Return empty dict if not found

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        # Reset the pending state on a coordinator update
        self._pending_state = False

        self._update_internal_state()
        self.async_write_ha_state()

    def _update_internal_state(self):
        """Update the entity's internal state attributes from task data."""
        # Start with all task fields (includes extra columns like screentime, notes, etc.)
        task_data = self._get_task_data()
        attributes = dict(task_data)

        # Add internal category if not already present
        attributes["category"] = self._category

        self._attr_extra_state_attributes = attributes

    async def async_press(self):
        """Handle the button press by updating local state and firing an event."""

        if self._pending_state:
            _LOGGER.warning(f"Task '{self.task_id}' is already pending. Press ignored.")
            return

        if self.state == "completed":
            _LOGGER.warning(
                f"Task '{self.task_id}' is already completed. Press ignored."
            )
            return

        _LOGGER.info(f"Button pressed for task: {self.task_id}")
        self._pending_state = True
        self.async_write_ha_state()

        for task in self.coordinator.data:
            if task.get("task") == self.task_id:
                task["state"] = "pending"
                task["visible"] = True
                break

        event_type = "google_task_list_button_pressed"
        event_data = {
            "entity_id": self.entity_id,
            "task_name": self.task_id,
            "action_id": f"CONFIRM_{self.task_id.replace(' ', '_').upper()}",
            "assigned_to": self._attr_extra_state_attributes.get("assigned_to"),
            "category": self._category,
            "unique_id": self._attr_unique_id,
        }

        self.hass.bus.async_fire(event_type, event_data)
