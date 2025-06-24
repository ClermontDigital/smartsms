"""The SmartSMS integration."""
from __future__ import annotations

import logging
from typing import Any
import asyncio

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
        }
        
        # Wait for webhook component to be fully ready, then register webhook
        await _ensure_webhook_ready_and_register(hass, entry)
        
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


async def _ensure_webhook_ready_and_register(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Ensure webhook component is ready and register webhook with retries."""
    max_retries = 10
    retry_delay = 1.0  # seconds
    
    for attempt in range(max_retries):
        try:
            # Check if webhook component is properly loaded
            webhook_component = hass.data.get('webhook')
            _LOGGER.error("🔧 Attempt %d: Webhook component check: %s", attempt + 1, webhook_component is not None)
            
            if webhook_component and hasattr(webhook_component, '_handlers'):
                _LOGGER.error("🔧 Webhook component ready! Registering webhook...")
                await async_register_webhook(hass, entry)
                return
            
            if attempt < max_retries - 1:
                _LOGGER.error("🔧 Webhook component not ready, waiting %.1fs (attempt %d/%d)", retry_delay, attempt + 1, max_retries)
                await asyncio.sleep(retry_delay)
                retry_delay *= 1.5  # Exponential backoff
            else:
                _LOGGER.error("🔧 Webhook component still not ready after %d attempts, proceeding anyway", max_retries)
                await async_register_webhook(hass, entry)
                
        except Exception as err:
            if attempt == max_retries - 1:
                raise
            _LOGGER.warning("🔧 Webhook registration attempt %d failed: %s, retrying...", attempt + 1, err)
            await asyncio.sleep(retry_delay)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.info("Unloading SmartSMS integration: %s", entry.title)
    
    try:
        # Unregister webhook first
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