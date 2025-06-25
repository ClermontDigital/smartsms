"""The SmartSMS integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry  # type: ignore
from homeassistant.const import Platform, EVENT_HOMEASSISTANT_STARTED  # type: ignore
from homeassistant.core import HomeAssistant, Event  # type: ignore
from homeassistant.exceptions import ConfigEntryNotReady  # type: ignore
from homeassistant.helpers import device_registry as dr  # type: ignore

from .const import DOMAIN
from .data_store import SmartSMSDataStore
from .webhook import async_register_webhook, async_unregister_webhook

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up SmartSMS from a config entry."""
    _LOGGER.info("Setting up SmartSMS integration: %s", entry.title)
    
    try:
        # Initialize domain data structure
        hass.data.setdefault(DOMAIN, {})
        
        # Initialize data store first
        data_store = SmartSMSDataStore(hass, entry.entry_id)
        
        # Set up entry data structure
        hass.data[DOMAIN][entry.entry_id] = {
            "config": entry.data,
            "data_store": data_store,
            "webhook_registered": False,
        }
        
        # Register webhook after Home Assistant is fully started
        await _schedule_webhook_registration(hass, entry)
        
        # Setup platforms
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        
        # Register device after platforms are set up
        device_registry = dr.async_get(hass)
        device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, entry.entry_id)},
            manufacturer="SmartSMS",
            name="SMS Gateway",
            model="SmartSMS",
            configuration_url="https://console.twilio.com/",
        )
        
        _LOGGER.info("SmartSMS integration setup complete for: %s", entry.title)
        return True
        
    except Exception as err:
        _LOGGER.error("Failed to set up SmartSMS integration: %s", err)
        # Clean up on failure
        if entry.entry_id in hass.data.get(DOMAIN, {}):
            hass.data[DOMAIN].pop(entry.entry_id)
        raise ConfigEntryNotReady(f"Failed to set up SmartSMS: {err}") from err


async def _schedule_webhook_registration(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Schedule webhook registration after Home Assistant startup."""
    
    if hass.is_running:
        # Home Assistant is already started, register immediately
        _LOGGER.error("🔧 Home Assistant already running, registering webhook immediately")
        await _register_webhook_safely(hass, entry)
    else:
        # Home Assistant is still starting, wait for startup event
        _LOGGER.error("🔧 Home Assistant still starting, waiting for startup event")
        
        async def on_homeassistant_started(event: Event) -> None:
            """Handle Home Assistant started event."""
            _LOGGER.error("🔧 Home Assistant started event received, registering webhook")
            await _register_webhook_safely(hass, entry)
        
        # Listen for the startup event
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, on_homeassistant_started)


async def _register_webhook_safely(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Register webhook with proper error handling."""
    try:
        # Check if already registered
        entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
        if entry_data.get("webhook_registered", False):
            _LOGGER.error("🔧 Webhook already registered for entry %s", entry.entry_id)
            return
        
        _LOGGER.error("🔧 Attempting webhook registration for entry %s", entry.entry_id)
        await async_register_webhook(hass, entry)
        
        # Mark as registered
        if entry.entry_id in hass.data.get(DOMAIN, {}):
            hass.data[DOMAIN][entry.entry_id]["webhook_registered"] = True
            
        _LOGGER.error("🔧 ✅ Webhook registration completed successfully")
        
    except Exception as err:
        _LOGGER.error("🔧 ❌ Failed to register webhook: %s", err)
        # Don't fail the integration setup, just log the error


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.info("Unloading SmartSMS integration: %s", entry.title)
    
    try:
        # Get entry data before cleanup
        entry_data = hass.data[DOMAIN].get(entry.entry_id, {})
        webhook_registered = entry_data.get("webhook_registered", False)
        
        # Unregister webhook if it was registered
        if webhook_registered:
            _LOGGER.error("🔧 Unregistering webhook for entry %s", entry.entry_id)
            await async_unregister_webhook(hass, entry)
        else:
            _LOGGER.error("🔧 No webhook to unregister for entry %s", entry.entry_id)
        
        # Unload platforms
        unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
        
        if unload_ok:
            # Clean up data store
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