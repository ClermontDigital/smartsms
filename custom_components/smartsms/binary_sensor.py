"""Binary sensor platform for the SmartSMS integration."""
from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later

from .const import (
    ATTR_BODY,
    ATTR_SENDER,
    ATTR_TIMESTAMP,
    BINARY_SENSOR_NEW_MESSAGE,
    BINARY_SENSOR_RESET_DELAY,
    DOMAIN,
    SIGNAL_MESSAGE_STORED,
)
from .sensor import one_line

NEW_MESSAGE_DESCRIPTION = BinarySensorEntityDescription(
    key=BINARY_SENSOR_NEW_MESSAGE,
    name="New Message",
    icon="mdi:message-alert",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SmartSMS binary sensors from a config entry."""
    async_add_entities([SmartSMSBinarySensor(entry, NEW_MESSAGE_DESCRIPTION)])


class SmartSMSBinarySensor(BinarySensorEntity):
    """On for a few seconds each time an SMS arrives."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, entry: ConfigEntry, description: BinarySensorEntityDescription) -> None:
        """Initialize the binary sensor."""
        self.entity_description = description
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_is_on = False
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})
        self._reset_cancel: CALLBACK_TYPE | None = None

    async def async_added_to_hass(self) -> None:
        """Turn on when a message is stored."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_MESSAGE_STORED.format(self._entry.entry_id),
                self._trigger_new_message,
            )
        )
        self.async_on_remove(self._cancel_reset)

    @callback
    def _trigger_new_message(self) -> None:
        self._cancel_reset()
        self._attr_is_on = True
        self.async_write_ha_state()
        self._reset_cancel = async_call_later(
            self.hass, BINARY_SENSOR_RESET_DELAY, self._reset_sensor
        )

    @callback
    def _reset_sensor(self, _now: Any) -> None:
        self._reset_cancel = None
        self._attr_is_on = False
        self.async_write_ha_state()

    @callback
    def _cancel_reset(self) -> None:
        if self._reset_cancel:
            self._reset_cancel()
            self._reset_cancel = None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        store = self._entry.runtime_data
        latest = store.latest_message
        attributes: dict[str, Any] = {
            "reset_delay": BINARY_SENSOR_RESET_DELAY,
            "message_count": store.message_count,
        }
        if latest:
            preview = one_line(latest.get(ATTR_BODY, ""))
            attributes.update({
                "last_message_preview": preview[:50] + "..." if len(preview) > 50 else preview,
                "last_sender": latest.get(ATTR_SENDER),
                "last_message_time": latest.get(ATTR_TIMESTAMP),
            })
        return attributes
