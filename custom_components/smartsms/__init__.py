"""The SmartSMS integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN
from .data_store import SmartSMSDataStore
from .webhook import async_register_webhook, async_unregister_webhook

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR]

# Debug: Log when module is imported
_LOGGER.warning("SMARTSMS MODULE IMPORTED - __init__.py loaded")


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up SmartSMS from a config entry."""
    _LOGGER.warning("SMARTSMS SETUP STARTING: %s", entry.title)
    _LOGGER.warning("SMARTSMS CONFIG DATA: %s", entry.data)
    
    try:
        # Initialize domain data structure
        hass.data.setdefault(DOMAIN, {})
        
        # Initialize data store
        data_store = SmartSMSDataStore(hass, entry.entry_id)
        
        # Set up entry data structure
        hass.data[DOMAIN][entry.entry_id] = {
            "config": entry.data,
            "data_store": data_store,
        }
        
        # Register webhook
        await async_register_webhook(hass, entry)
        
        # Setup platforms
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        
        # Register device
        device_registry = dr.async_get(hass)
        device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, entry.entry_id)},
            manufacturer="SmartSMS",
            name="SMS Gateway",
            model="SmartSMS",
            configuration_url="https://console.twilio.com/",
        )
        
        _LOGGER.warning("SMARTSMS SETUP COMPLETE: %s", entry.title)
        return True
        
    except Exception as err:
        _LOGGER.error("SMARTSMS SETUP FAILED: %s", err)
        _LOGGER.exception("SMARTSMS FULL ERROR TRACE:")
        # Clean up on failure
        if entry.entry_id in hass.data.get(DOMAIN, {}):
            hass.data[DOMAIN].pop(entry.entry_id)
        raise ConfigEntryNotReady(f"Failed to set up SmartSMS: {err}") from err


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.info("Unloading SmartSMS integration: %s", entry.title)
    
    try:
        # Unregister webhook
        await async_unregister_webhook(hass, entry)
        
        # Unload platforms
        unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
        
        if unload_ok:
            # Clean up data store
            entry_data = hass.data[DOMAIN].get(entry.entry_id, {})
            data_store = entry_data.get("data_store")
            if data_store:
                await data_store.cleanup()
            
            # Remove entry data
            hass.data[DOMAIN].pop(entry.entry_id, None)
            if not hass.data[DOMAIN]:
                hass.data.pop(DOMAIN, None)
                
        _LOGGER.info("SmartSMS integration unloaded: %s", entry.title)
        return unload_ok
        
    except Exception as err:
        _LOGGER.error("Failed to unload SmartSMS integration: %s", err)
        return False 