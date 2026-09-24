"""SMS sending action for the SmartSMS integration."""
from __future__ import annotations

import base64
import json
import logging
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_API_PASSWORD,
    CONF_API_USERNAME,
    CONF_DEFAULT_SENDER,
    DOMAIN,
    MAX_MESSAGE_LENGTH,
    MM_API_BASE_URL,
    MM_SEND_ENDPOINT,
    SEND_TIMEOUT,
    SERVICE_SEND_SMS,
)

_LOGGER = logging.getLogger(__name__)

SEND_SMS_SCHEMA = vol.Schema({
    vol.Required("to"): cv.string,
    vol.Required("message"): cv.string,
    vol.Optional("sender"): cv.string,
    vol.Optional("custom_ref"): cv.string,
})


@callback
def async_register_services(hass: HomeAssistant) -> None:
    """Register the send action (once, shared by all entries)."""
    if hass.services.has_service(DOMAIN, SERVICE_SEND_SMS):
        return

    async def async_send_sms(call: ServiceCall) -> ServiceResponse:
        """Send an SMS via the Mobile Message API."""
        entry = _loaded_entry(hass)
        to_number = call.data["to"].strip()
        message = call.data["message"]
        # Options win: that's where the sender is changed after setup
        sender = (
            call.data.get("sender")
            or entry.options.get(CONF_DEFAULT_SENDER)
            or entry.data.get(CONF_DEFAULT_SENDER)
        )

        if not sender:
            raise ServiceValidationError(
                "No sender ID given and no default sender is configured"
            )
        if not _is_valid_phone_number(to_number):
            raise ServiceValidationError(
                "The destination is not a valid phone number (use 04xxxxxxxx or +614xxxxxxxx)"
            )
        if not message.strip():
            raise ServiceValidationError("The message is empty")
        if len(message) > MAX_MESSAGE_LENGTH:
            raise ServiceValidationError(
                f"The message is {len(message)} characters; the maximum is {MAX_MESSAGE_LENGTH}"
            )

        result = await _async_send_sms_api(
            hass, entry, to_number, message, sender, call.data.get("custom_ref", "")
        )
        return result if call.return_response else None

    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_SMS,
        async_send_sms,
        schema=SEND_SMS_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )


@callback
def async_unregister_services(hass: HomeAssistant) -> None:
    """Remove the send action."""
    hass.services.async_remove(DOMAIN, SERVICE_SEND_SMS)


def _loaded_entry(hass: HomeAssistant) -> ConfigEntry:
    """Return the config entry to send from."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is ConfigEntryState.LOADED:
            return entry
    raise ServiceValidationError("SmartSMS is not set up")


async def _async_send_sms_api(
    hass: HomeAssistant,
    entry: ConfigEntry,
    to_number: str,
    message: str,
    sender: str,
    custom_ref: str,
) -> dict[str, Any]:
    """Send one message; raise HomeAssistantError if Mobile Message doesn't accept it."""
    item: dict[str, Any] = {"to": to_number, "message": message, "sender": sender}
    if custom_ref:
        item["custom_ref"] = custom_ref

    session = async_get_clientsession(hass)
    try:
        async with session.post(
            f"{MM_API_BASE_URL}{MM_SEND_ENDPOINT}",
            json={"messages": [item]},
            headers={"Authorization": _basic_auth(entry)},
            timeout=aiohttp.ClientTimeout(total=SEND_TIMEOUT),
        ) as response:
            status = response.status
            text = await response.text()
    except TimeoutError as err:
        raise HomeAssistantError("Timed out sending the SMS to Mobile Message") from err
    except aiohttp.ClientError as err:
        raise HomeAssistantError(f"Could not reach Mobile Message: {err}") from err

    if status in (401, 403):
        raise HomeAssistantError(
            f"Mobile Message rejected the API credentials (HTTP {status})"
        )
    try:
        data = json.loads(text)
    except ValueError:
        data = None
    if status != 200:
        detail = data.get("error") if isinstance(data, dict) else None
        raise HomeAssistantError(
            f"Mobile Message returned HTTP {status}" + (f": {detail}" if detail else "")
        )
    if not isinstance(data, dict):
        raise HomeAssistantError("Mobile Message returned an unexpected response")

    results = data.get("results") or [{}]
    first = results[0] if isinstance(results[0], dict) else {}
    if data.get("status") != "complete" or first.get("status") != "success":
        reason = first.get("error") or first.get("status") or data.get("status") or "unknown error"
        raise HomeAssistantError(f"Mobile Message did not send the SMS: {reason}")

    _LOGGER.debug("SMS accepted by Mobile Message, id %s", first.get("message_id"))
    return {
        "message_id": first.get("message_id"),
        "to": first.get("to", to_number),
        "sender": first.get("sender", sender),
        "cost": first.get("cost"),
    }


def _basic_auth(entry: ConfigEntry) -> str:
    """Basic auth header value (aiohttp.BasicAuth is deprecated)."""
    credentials = f"{entry.data[CONF_API_USERNAME]}:{entry.data[CONF_API_PASSWORD]}"
    return "Basic " + base64.b64encode(credentials.encode()).decode()


def _is_valid_phone_number(phone: str) -> bool:
    """Validate a destination number (Australian local or international)."""
    clean = "".join(c for c in phone if c.isdigit() or c == "+")
    if clean.startswith("+"):
        return 9 <= len(clean) <= 16 and clean[1:].isdigit()
    if clean.startswith("0"):
        return len(clean) == 10 and clean.isdigit()
    return 8 <= len(clean) <= 15 and clean.isdigit()
