"""Diagnostics for the SmartSMS integration."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    ATTR_BODY,
    ATTR_MATCHED_KEYWORDS,
    ATTR_SENDER,
    ATTR_TO_NUMBER,
    CONF_API_PASSWORD,
    CONF_API_USERNAME,
    CONF_DEFAULT_SENDER,
    CONF_KEYWORDS,
    CONF_SENDER_BLACKLIST,
    CONF_SENDER_WHITELIST,
    CONF_WEBHOOK_ID,
)

# Secrets, phone numbers, keywords and message contents
TO_REDACT = {
    CONF_DEFAULT_SENDER,
    CONF_KEYWORDS,
    ATTR_MATCHED_KEYWORDS,
    CONF_API_USERNAME,
    CONF_API_PASSWORD,
    CONF_WEBHOOK_ID,
    "webhook_secret",
    ATTR_BODY,
    ATTR_SENDER,
    ATTR_TO_NUMBER,
    CONF_SENDER_WHITELIST,
    CONF_SENDER_BLACKLIST,
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    store = getattr(entry, "runtime_data", None)  # absent while not loaded
    setup_sender = entry.data.get(CONF_DEFAULT_SENDER)
    options_sender = entry.options.get(CONF_DEFAULT_SENDER)
    return {
        "data": async_redact_data(dict(entry.data), TO_REDACT),
        "options": async_redact_data(dict(entry.options), TO_REDACT),
        "sender_in_use_from": "options" if options_sender else "setup",
        "options_sender_differs_from_setup": bool(options_sender) and options_sender != setup_sender,
        "keyword_count": len(entry.options.get(CONF_KEYWORDS) or []),
        "message_count": store.message_count if store else None,
        "latest_message": async_redact_data(store.latest_message, TO_REDACT) if store else None,
    }
