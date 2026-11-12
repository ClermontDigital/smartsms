"""The SmartSMS integration."""
from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components import frontend
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from .api import async_register_api
from .const import CARD_FILENAME, CARD_URL, CONF_API_USERNAME, DOMAIN
from .data_store import SmartSMSDataStore
from .sms_service import async_register_services, async_unregister_services
from .webhook import async_register_webhook, async_unregister_webhook

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the messages card's WebSocket API."""
    async_register_api(hass)
    return True


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
    try:
        await _async_setup_frontend(hass)
    except Exception:  # noqa: BLE001 - SMS work without the card being auto-registered
        _LOGGER.warning("SmartSMS: messages card setup failed", exc_info=True)
    return True


async def _async_setup_frontend(hass: HomeAssistant) -> None:
    """Serve the messages card and make sure dashboards load it (once per HA run)."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get("frontend"):
        return
    domain_data["frontend"] = True

    card_path = Path(__file__).parent / "www" / CARD_FILENAME
    try:
        version = (await async_get_integration(hass, DOMAIN)).version
    except Exception:  # noqa: BLE001
        version = None
    url = f"{CARD_URL}?v={version}" if version else CARD_URL
    await hass.http.async_register_static_paths([StaticPathConfig(CARD_URL, str(card_path), False)])
    if not await _async_register_resource(hass, url):
        try:
            frontend.add_extra_js_url(hass, url)
        except Exception:  # noqa: BLE001 - frontend not loaded (tests, minimal installs)
            _LOGGER.warning("SmartSMS: add %s as a dashboard resource to use the messages card", CARD_URL)


async def _async_register_resource(hass: HomeAssistant, url: str) -> bool:
    """Add or refresh the Lovelace resource so storage-mode dashboards load the card."""
    try:
        from homeassistant.components.lovelace import LOVELACE_DATA

        lovelace = hass.data.get(LOVELACE_DATA)
        resources = getattr(lovelace, "resources", None)
        if resources is None or not hasattr(resources, "async_create_item"):
            return False  # YAML-mode resources: added by hand
        if hasattr(resources, "loaded") and not resources.loaded:
            await resources.async_load()
        base = url.split("?")[0]
        for item in resources.async_items():
            existing = item.get("url", "")
            if existing.split("?")[0] == base:
                if existing != url:  # new version: refresh the cache buster
                    await resources.async_update_item(item["id"], {"url": url})
                return True
        await resources.async_create_item({"res_type": "module", "url": url})
        return True
    except Exception:  # noqa: BLE001 - the card can still be added by hand
        _LOGGER.warning("SmartSMS: couldn't register the messages card resource", exc_info=True)
        return False


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
