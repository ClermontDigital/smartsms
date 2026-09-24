"""Sensor platform for the SmartSMS integration."""
from __future__ import annotations

import re
from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    ATTR_BODY,
    ATTR_MATCHED_KEYWORDS,
    ATTR_MESSAGE_SID,
    ATTR_PROVIDER,
    ATTR_SENDER,
    ATTR_TIMESTAMP,
    ATTR_TO_NUMBER,
    DOMAIN,
    SENSOR_LAST_MESSAGE,
    SENSOR_LAST_SENDER,
    SENSOR_MESSAGE_COUNT,
    SENSOR_STATE_MAX_LENGTH,
    SIGNAL_MESSAGE_STORED,
)
from .data_store import SmartSMSDataStore

SENSOR_DESCRIPTIONS = [
    SensorEntityDescription(
        key=SENSOR_LAST_MESSAGE,
        name="Last Message",
        icon="mdi:message-text",
    ),
    SensorEntityDescription(
        key=SENSOR_LAST_SENDER,
        name="Last Sender",
        icon="mdi:phone",
    ),
    SensorEntityDescription(
        key=SENSOR_MESSAGE_COUNT,
        name="Message Count",
        icon="mdi:counter",
        native_unit_of_measurement="messages",
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SmartSMS sensors from a config entry."""
    async_add_entities(
        SmartSMSSensor(entry, description) for description in SENSOR_DESCRIPTIONS
    )


def one_line(text: str) -> str:
    """Collapse line breaks and runs of whitespace (entity states are one line)."""
    return re.sub(r"\s+", " ", text).strip()


class SmartSMSSensor(SensorEntity):
    """A SmartSMS sensor, updated when a message arrives (never polled)."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, entry: ConfigEntry, description: SensorEntityDescription) -> None:
        """Initialize the sensor."""
        self.entity_description = description
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})

    @property
    def _store(self) -> SmartSMSDataStore:
        return self._entry.runtime_data

    @property
    def native_value(self) -> str | int | None:
        """Return the state of the sensor."""
        latest = self._store.latest_message
        key = self.entity_description.key
        if key == SENSOR_LAST_MESSAGE:
            body = latest.get(ATTR_BODY)
            return one_line(body)[:SENSOR_STATE_MAX_LENGTH] if body else None
        if key == SENSOR_LAST_SENDER:
            return latest.get(ATTR_SENDER)
        return self._store.message_count

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra state attributes (names kept from 0.9.x for automations)."""
        latest = self._store.latest_message
        if not latest:
            return None
        body = latest.get(ATTR_BODY, "")
        key = self.entity_description.key

        if key == SENSOR_LAST_MESSAGE:
            attributes = {
                "full_message": body,
                "raw_message": body,
                # Braces and % can't start a Jinja expression here
                "template_safe": body.replace("{", "(").replace("}", ")").replace("%", "pct"),
                ATTR_SENDER: latest.get(ATTR_SENDER),
                ATTR_TIMESTAMP: latest.get(ATTR_TIMESTAMP),
                ATTR_MESSAGE_SID: latest.get(ATTR_MESSAGE_SID),
                ATTR_TO_NUMBER: latest.get(ATTR_TO_NUMBER),
                ATTR_PROVIDER: latest.get(ATTR_PROVIDER),
                ATTR_MATCHED_KEYWORDS: latest.get(ATTR_MATCHED_KEYWORDS),
            }
        elif key == SENSOR_LAST_SENDER:
            preview = one_line(body)
            attributes = {
                "message_preview": preview[:100] + "..." if len(preview) > 100 else preview,
                ATTR_TIMESTAMP: latest.get(ATTR_TIMESTAMP),
                ATTR_MESSAGE_SID: latest.get(ATTR_MESSAGE_SID),
                ATTR_TO_NUMBER: latest.get(ATTR_TO_NUMBER),
                ATTR_PROVIDER: latest.get(ATTR_PROVIDER),
            }
        else:
            attributes = {
                "last_message_time": latest.get(ATTR_TIMESTAMP),
                "last_sender": latest.get(ATTR_SENDER),
                ATTR_PROVIDER: latest.get(ATTR_PROVIDER),
            }
        return {k: v for k, v in attributes.items() if v is not None}

    async def async_added_to_hass(self) -> None:
        """Refresh when a message is stored."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_MESSAGE_STORED.format(self._entry.entry_id),
                self.async_write_ha_state,
            )
        )
