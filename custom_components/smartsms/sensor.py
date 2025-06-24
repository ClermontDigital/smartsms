"""Sensor platform for SmartSMS integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback


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
    sensors.append(SmartSMSWebhookURLSensor(hass, entry))
    
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
            # Truncate long messages for the state
            return body[:255] if body else None
        
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
            attributes = {
                "full_message": latest_message.get(ATTR_BODY, ""),
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
            attributes = {
                "message_preview": body[:100] + "..." if len(body) > 100 else body,
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

    async def async_update(self) -> None:
        """Update the sensor."""
        # The sensor gets updated via the webhook handler and data events
        # This method is called by HA's update cycle
        pass 


class SmartSMSWebhookURLSensor(SensorEntity):
    """Diagnostic sensor showing the webhook URL."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        self.hass = hass
        self._config_entry = config_entry
        self._attr_name = f"{config_entry.title} Webhook URL"
        self._attr_unique_id = f"{config_entry.entry_id}_webhook_url"
        self._attr_icon = "mdi:webhook"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        
        # Set up device info
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, config_entry.entry_id)},
            name="SMS Gateway",
            manufacturer="SmartSMS",
            model="Twilio Integration",
            configuration_url="https://console.twilio.com/",
        )
        
        # Generate the webhook URL
        webhook_id = config_entry.data.get(CONF_WEBHOOK_ID)
        base_url = hass.config.external_url or "http://your-home-assistant.local:8123"
        self._attr_native_value = f"{base_url}/api/webhook/{webhook_id}"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        webhook_id = self._config_entry.data.get(CONF_WEBHOOK_ID)
        return {
            "webhook_id": webhook_id,
            "integration": "SmartSMS",
            "setup_instructions": "Copy this URL to your Twilio phone number's messaging webhook configuration",
        } 