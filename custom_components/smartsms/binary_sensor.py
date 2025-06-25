"""Binary sensor platform for SmartSMS integration."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.components.binary_sensor import (  # type: ignore
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry  # type: ignore
from homeassistant.core import HomeAssistant, callback  # type: ignore
from homeassistant.helpers.entity import DeviceInfo  # type: ignore
from homeassistant.helpers.entity_platform import AddEntitiesCallback  # type: ignore
from homeassistant.helpers.event import async_call_later  # type: ignore

from .const import (
    ATTR_BODY,
    ATTR_SENDER,
    ATTR_TIMESTAMP,
    BINARY_SENSOR_NEW_MESSAGE,
    BINARY_SENSOR_RESET_DELAY,
    DOMAIN,
    EVENT_MESSAGE_RECEIVED,
)

_LOGGER = logging.getLogger(__name__)

BINARY_SENSOR_DESCRIPTIONS = [
    BinarySensorEntityDescription(
        key=BINARY_SENSOR_NEW_MESSAGE,
        name="New Message",
        icon="mdi:message-alert",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SmartSMS binary sensors from a config entry."""
    binary_sensors = []
    
    for description in BINARY_SENSOR_DESCRIPTIONS:
        binary_sensors.append(SmartSMSBinarySensor(entry, description))
    
    async_add_entities(binary_sensors)


class SmartSMSBinarySensor(BinarySensorEntity):
    """Representation of a SmartSMS binary sensor."""

    def __init__(self, entry: ConfigEntry, description: BinarySensorEntityDescription) -> None:
        """Initialize the binary sensor."""
        self.entity_description = description
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_name = f"{entry.title} {description.name}"
        self._attr_is_on = False
        self._reset_cancel = None  # Cancel callback from async_call_later
        
        # Set up device info
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="SMS Gateway",
            manufacturer="SmartSMS",
            model="Twilio Integration",
            configuration_url="https://console.twilio.com/",
        )

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        
        # Listen for message received events
        self.async_on_remove(
            self.hass.bus.async_listen(
                EVENT_MESSAGE_RECEIVED,
                self._handle_message_received,
            )
        )

    @callback
    def _handle_message_received(self, event) -> None:
        """Handle message received event."""
        # Only process if this event is for our config entry
        # We can identify this by checking the entry data
        if DOMAIN in self.hass.data and self._entry.entry_id in self.hass.data[DOMAIN]:
            self._trigger_new_message()

    @callback
    def _trigger_new_message(self) -> None:
        """Trigger the binary sensor to indicate a new message."""
        # Cancel any existing reset callback
        if self._reset_cancel:
            self._reset_cancel()
            self._reset_cancel = None
        
        # Turn on the binary sensor
        self._attr_is_on = True
        self.async_write_ha_state()
        
        # Schedule reset after delay
        self._reset_cancel = async_call_later(
            self.hass,
            BINARY_SENSOR_RESET_DELAY,
            self._reset_sensor,
        )

    @callback
    def _reset_sensor(self, _) -> None:
        """Reset the binary sensor to off state."""
        self._attr_is_on = False
        self.async_write_ha_state()
        self._reset_cancel = None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra state attributes."""
        if DOMAIN not in self.hass.data:
            return None
        
        entry_data = self.hass.data[DOMAIN].get(self._entry.entry_id, {})
        latest_message = entry_data.get("latest_message", {})
        
        if not latest_message:
            return {
                "reset_delay": BINARY_SENSOR_RESET_DELAY,
                "message_count": entry_data.get("message_count", 0),
            }
        
        # Include info about the last message
        body = latest_message.get(ATTR_BODY, "")
        
        # Sanitize the body for display (apply same ASCII-only filtering)
        if body:
            sanitized_body = self._sanitize_preview_text(body)
            preview = sanitized_body[:50] + "..." if len(sanitized_body) > 50 else sanitized_body
        else:
            preview = ""
        
        return {
            "reset_delay": BINARY_SENSOR_RESET_DELAY,
            "message_count": entry_data.get("message_count", 0),
            "last_message_preview": preview,
            "last_sender": latest_message.get(ATTR_SENDER),
            "last_message_time": latest_message.get(ATTR_TIMESTAMP),
        }

    def _sanitize_preview_text(self, text: str) -> str:
        """Clean text for preview display using ASCII-only filtering."""
        if not text:
            return text
        
        import re
        import html
        
        _LOGGER.debug("BINARY SENSOR ORIGINAL: %r", text)
        
        # Apply same aggressive ASCII-only filtering as polling function
        ascii_chars = []
        for char in text:
            char_code = ord(char)
            if 32 <= char_code <= 126:  # Printable ASCII range
                # But specifically remove asterisks and other markdown chars
                if char not in ['*', '_', '`', '#', '[', ']', '!', '|', '\\', '^', '>', '<', '~']:
                    ascii_chars.append(char)
                else:
                    _LOGGER.debug("BINARY SENSOR REMOVED markdown char: %r", char)
            elif char_code == 9:  # Tab -> space
                ascii_chars.append(' ')
            elif char_code in (10, 13):  # LF, CR -> space
                ascii_chars.append(' ')
            else:
                _LOGGER.debug("BINARY SENSOR REMOVED non-ASCII: %r (code=%d)", char, char_code)
        
        clean_text = ''.join(ascii_chars)
        
        # Normalize whitespace
        clean_text = re.sub(r'\s+', ' ', clean_text)
        clean_text = clean_text.strip()
        
        _LOGGER.debug("BINARY SENSOR FINAL: %r", clean_text)
        
        return clean_text

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return True

    async def async_will_remove_from_hass(self) -> None:
        """When entity will be removed from hass."""
        # Cancel any pending reset callback
        if self._reset_cancel:
            self._reset_cancel()
            self._reset_cancel = None
        
        await super().async_will_remove_from_hass() 