"""Sensor platform for SmartSMS integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (  # type: ignore
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry  # type: ignore
from homeassistant.core import HomeAssistant, callback  # type: ignore
from homeassistant.helpers.entity import DeviceInfo, EntityCategory  # type: ignore
from homeassistant.helpers.entity_platform import AddEntitiesCallback  # type: ignore


from .const import (
    ATTR_BODY,
    ATTR_MESSAGE_SID,
    ATTR_PROVIDER,
    ATTR_SENDER,
    ATTR_TIMESTAMP,
    ATTR_TO_NUMBER,
    DOMAIN,
    SENSOR_LAST_MESSAGE,
    SENSOR_LAST_SENDER,
    SENSOR_MESSAGE_COUNT,
    CONF_WEBHOOK_ID,
)

_LOGGER = logging.getLogger(__name__)

SENSOR_DESCRIPTIONS = [
    SensorEntityDescription(
        key=SENSOR_LAST_MESSAGE,
        name="Last Message",
        icon="mdi:message-text",
        native_unit_of_measurement=None,
    ),
    SensorEntityDescription(
        key=SENSOR_LAST_SENDER,
        name="Last Sender",
        icon="mdi:phone",
        native_unit_of_measurement=None,
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
    sensors = [
        SmartSMSSensor(entry, description) for description in SENSOR_DESCRIPTIONS
    ]
    
    async_add_entities(sensors)


class SmartSMSSensor(SensorEntity):
    """Representation of a SmartSMS sensor."""

    def __init__(self, entry: ConfigEntry, description: SensorEntityDescription) -> None:
        """Initialize the sensor."""
        self.entity_description = description
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_name = f"{entry.title} {description.name}"
        
        # Set up device info
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="SMS Gateway",
            manufacturer="SmartSMS",
            model="SmartSMS",
            configuration_url="https://console.twilio.com/",
        )

    @property
    def native_value(self) -> str | int | None:
        """Return the state of the sensor."""
        if DOMAIN not in self.hass.data:
            return None
        
        entry_data = self.hass.data[DOMAIN].get(self._entry.entry_id, {})
        latest_message = entry_data.get("latest_message", {})
        
        if self.entity_description.key == SENSOR_LAST_MESSAGE:
            body = latest_message.get(ATTR_BODY, "")
            if body:
                _LOGGER.debug("SENSOR RECEIVED BODY: %r (len=%d)", body, len(body))
                # Sanitize markdown characters to prevent formatting issues
                sanitized_body = self._sanitize_text(body)
                _LOGGER.debug("SENSOR FINAL SANITIZED: %r (len=%d)", sanitized_body, len(sanitized_body))
                # Truncate long messages for the state
                return sanitized_body[:255]
            return None
        
        elif self.entity_description.key == SENSOR_LAST_SENDER:
            return latest_message.get(ATTR_SENDER)
        
        elif self.entity_description.key == SENSOR_MESSAGE_COUNT:
            return entry_data.get("message_count", 0)
        
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra state attributes."""
        if DOMAIN not in self.hass.data:
            return None
        
        entry_data = self.hass.data[DOMAIN].get(self._entry.entry_id, {})
        latest_message = entry_data.get("latest_message", {})
        
        if not latest_message:
            return None
        
        attributes = {}
        
        if self.entity_description.key == SENSOR_LAST_MESSAGE:
            # For message sensor, include full message and metadata
            raw_body = latest_message.get(ATTR_BODY, "")
            attributes = {
                "full_message": self._sanitize_text(raw_body) if raw_body else "",
                "raw_message": raw_body,  # Keep original for automations that might need it
                "template_safe": self._make_template_safe(raw_body) if raw_body else "",  # Safe for Jinja2
                ATTR_SENDER: latest_message.get(ATTR_SENDER),
                ATTR_TIMESTAMP: latest_message.get(ATTR_TIMESTAMP),
                ATTR_MESSAGE_SID: latest_message.get(ATTR_MESSAGE_SID),
                ATTR_TO_NUMBER: latest_message.get(ATTR_TO_NUMBER),
                ATTR_PROVIDER: latest_message.get(ATTR_PROVIDER),
            }
            
            # Add matched keywords if available
            if "matched_keywords" in latest_message:
                attributes["matched_keywords"] = latest_message["matched_keywords"]
        
        elif self.entity_description.key == SENSOR_LAST_SENDER:
            # For sender sensor, include message preview and timestamp
            body = latest_message.get(ATTR_BODY, "")
            if body:
                sanitized_body = self._sanitize_text(body)
                preview = sanitized_body[:100] + "..." if len(sanitized_body) > 100 else sanitized_body
            else:
                preview = ""
            attributes = {
                "message_preview": preview,
                ATTR_TIMESTAMP: latest_message.get(ATTR_TIMESTAMP),
                ATTR_MESSAGE_SID: latest_message.get(ATTR_MESSAGE_SID),
                ATTR_TO_NUMBER: latest_message.get(ATTR_TO_NUMBER),
                ATTR_PROVIDER: latest_message.get(ATTR_PROVIDER),
            }
        
        elif self.entity_description.key == SENSOR_MESSAGE_COUNT:
            # For count sensor, include basic stats
            attributes = {
                "last_message_time": latest_message.get(ATTR_TIMESTAMP),
                "last_sender": latest_message.get(ATTR_SENDER),
                ATTR_PROVIDER: latest_message.get(ATTR_PROVIDER),
            }
        
        # Remove None values
        return {k: v for k, v in attributes.items() if v is not None}

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return True

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        
        # Listen for data update events
        self.async_on_remove(
            self.hass.bus.async_listen(
                f"{DOMAIN}_data_updated",
                self._handle_data_updated,
            )
        )

    @callback
    def _handle_data_updated(self, event) -> None:
        """Handle data updated event."""
        # Only update if this event is for our config entry
        if event.data.get("entry_id") == self._entry.entry_id:
            self.async_write_ha_state()

    def _sanitize_text(self, text: str) -> str:
        """Sanitize text to prevent markdown formatting issues in Home Assistant UI."""
        if not text:
            return text
        
        import re
        import html
        
        # The text should already be ASCII-clean from webhook processing,
        # but let's be extra defensive and ensure no formatting issues
        
        # Replace any markdown-triggering characters with safe alternatives
        # Do this BEFORE HTML escaping to avoid double-escaping
        sanitized = text
        
        # Replace markdown characters with visually similar safe alternatives
        markdown_replacements = {
            '*': '∗',    # Mathematical asterisk (not markdown)
            '_': '‗',    # Double low line (not markdown)
            '`': "'",    # Single quote instead of backtick
            '~': '∼',    # Tilde operator (not strikethrough)
            '#': '♯',    # Musical sharp (not heading)
            '[': '⟨',    # Mathematical left angle bracket
            ']': '⟩',    # Mathematical right angle bracket
            '!': 'ǃ',    # Latin letter retroflex click (looks like !)
            '|': '⎸',    # Left vertical box line
            '\\': '⧵',   # Reverse solidus operator
            '^': '＾',   # Fullwidth circumflex accent
            '>': '＞',   # Fullwidth greater-than sign
            '<': '＜',   # Fullwidth less-than sign
        }
        
        for char, replacement in markdown_replacements.items():
            sanitized = sanitized.replace(char, replacement)
        
        # Normalize whitespace
        sanitized = re.sub(r'\s+', ' ', sanitized)
        sanitized = sanitized.strip()
        
        # Final HTML escape for any remaining special characters
        sanitized = html.escape(sanitized)
        
        return sanitized

    def _make_template_safe(self, text: str) -> str:
        """Make text safe for use in Jinja2 templates and YAML."""
        if not text:
            return text
        
        # Start with basic sanitization
        safe_text = self._sanitize_text(text)
        
        # Additional template safety measures
        # Replace characters that can break Jinja2 templates
        template_unsafe_chars = {
            '{': '(',     # Replace with parenthesis
            '}': ')',     # Replace with parenthesis
            '%': 'pct',   # Replace with text
            '"': "'",     # Replace double quotes with single quotes
            '\\': '/',    # Replace backslash with forward slash
        }
        
        for char, replacement in template_unsafe_chars.items():
            safe_text = safe_text.replace(char, replacement)
        
        return safe_text

    async def async_update(self) -> None:
        """Update the sensor."""
        # The sensor gets updated via the webhook handler and data events
        # This method is called by HA's update cycle
        pass 