"""The SmartSMS integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import CONF_API_USERNAME, DOMAIN
from .data_store import SmartSMSDataStore
from .sms_service import async_register_services, async_unregister_services
from .webhook import async_register_webhook, async_unregister_webhook

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up SmartSMS from a config entry."""
    data_store = SmartSMSDataStore(hass, entry.entry_id)
    await data_store.async_load()
    entry.runtime_data = data_store

    if entry.unique_id is None:  # entries created by 0.9.x
        unique_id = entry.data[CONF_API_USERNAME].strip().lower()
        if not any(e.unique_id == unique_id for e in hass.config_entries.async_entries(DOMAIN)):
            hass.config_entries.async_update_entry(entry, unique_id=unique_id)

    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        manufacturer="Mobile Message",
        model="SMS gateway (webhook)",
        name=entry.title,
        configuration_url="https://mobilemessage.com.au/",
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    async_register_webhook(hass, entry)
    async_register_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False

    async_unregister_webhook(hass, entry)
    await entry.runtime_data.async_flush()
    # The send action is shared by every entry; drop it with the last one
    if not any(
        other.entry_id != entry.entry_id and other.state is ConfigEntryState.LOADED
        for other in hass.config_entries.async_entries(DOMAIN)
    ):
        async_unregister_services(hass)
    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Delete the stored messages when the integration is removed."""
    await SmartSMSDataStore(hass, entry.entry_id).async_remove()
