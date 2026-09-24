"""Webhook handling for the SmartSMS integration."""
from __future__ import annotations

import html
import json
import logging
import re
from datetime import datetime
from typing import Any

from aiohttp import hdrs, web
from homeassistant.components import webhook
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_BODY,
    ATTR_MATCHED_KEYWORDS,
    ATTR_MESSAGE_SID,
    ATTR_PROVIDER,
    ATTR_SENDER,
    ATTR_TIMESTAMP,
    ATTR_TO_NUMBER,
    CONF_KEYWORDS,
    CONF_SENDER_BLACKLIST,
    CONF_SENDER_WHITELIST,
    CONF_WEBHOOK_ID,
    DOMAIN,
    EVENT_KEYWORD_MATCHED,
    EVENT_MESSAGE_RECEIVED,
    INBOUND_BODY_MAX_LENGTH,
    MM_MESSAGE,
    MM_MESSAGE_ID,
    MM_RECEIVED_AT,
    MM_SENDER,
    MM_TO,
    WEBHOOK_MAX_BYTES,
)

_LOGGER = logging.getLogger(__name__)


@callback
def async_register_webhook(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Register the webhook Mobile Message posts received SMS to."""
    webhook_id = entry.data[CONF_WEBHOOK_ID]

    async def _handle(
        hass: HomeAssistant, webhook_id: str, request: web.Request
    ) -> web.Response:
        return await _async_handle_webhook(hass, entry, request)

    webhook.async_unregister(hass, webhook_id)  # no-op unless left over
    webhook.async_register(hass, DOMAIN, f"SmartSMS ({entry.title})", webhook_id, _handle)


@callback
def async_unregister_webhook(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Unregister the webhook."""
    webhook.async_unregister(hass, entry.data[CONF_WEBHOOK_ID])


def _text(status: int, text: str) -> web.Response:
    return web.Response(status=status, text=text, content_type="text/plain")


async def _async_handle_webhook(
    hass: HomeAssistant, entry: ConfigEntry, request: web.Request
) -> web.Response:
    """Handle one inbound SMS from Mobile Message.

    Nabu Casa cloudhooks deliver a MockRequest, which only has headers,
    content, text() and json() - so stick to those.
    """
    length = request.headers.get(hdrs.CONTENT_LENGTH)
    if length and length.isdigit() and int(length) > WEBHOOK_MAX_BYTES:
        return _text(413, "PAYLOAD_TOO_LARGE")
    stream = request.content  # MockRequest builds a new reader on every access
    raw = b""
    while chunk := await stream.read(WEBHOOK_MAX_BYTES + 1 - len(raw)):
        raw += chunk
        if len(raw) > WEBHOOK_MAX_BYTES:  # chunked bodies have no content-length
            return _text(413, "PAYLOAD_TOO_LARGE")

    try:
        data = json.loads(raw.decode("utf-8", errors="replace"))
    except ValueError:
        _LOGGER.warning("SmartSMS webhook received a body that isn't JSON")
        return _text(400, "INVALID_DATA")
    if not isinstance(data, dict):
        return _text(400, "INVALID_DATA")

    message_data = _extract_message_data(data)
    if message_data is None:
        _LOGGER.warning(
            "SmartSMS webhook payload has no message or sender (keys: %s)", sorted(data)
        )
        return _text(400, "INVALID_MESSAGE")

    if not _should_process_message(entry, message_data[ATTR_SENDER]):
        _LOGGER.debug("SMS filtered out by the sender allow/block lists")
        return _text(200, "FILTERED")

    matched = _check_keywords(_option(entry, CONF_KEYWORDS), message_data[ATTR_BODY])
    if matched:
        message_data[ATTR_MATCHED_KEYWORDS] = matched

    hass.bus.async_fire(EVENT_MESSAGE_RECEIVED, message_data)
    if matched:
        hass.bus.async_fire(EVENT_KEYWORD_MATCHED, message_data)
    entry.runtime_data.async_store_message(message_data)

    _LOGGER.debug("Received SMS (%d chars)", len(message_data[ATTR_BODY]))
    return _text(200, "OK")


def _option(entry: ConfigEntry, key: str) -> list[str]:
    """Read a list setting: Options first, then the original setup data."""
    value = entry.options.get(key, entry.data.get(key)) or []
    if isinstance(value, str):
        value = value.split(",")
    return [item.strip() for item in value if item and item.strip()]


def _extract_message_data(data: dict[str, Any]) -> dict[str, Any] | None:
    """Pull the SMS fields out of a Mobile Message webhook payload."""
    body = data.get(MM_MESSAGE)
    sender = data.get(MM_SENDER)
    if not isinstance(body, str) or not body.strip() or not sender:
        return None

    timestamp = dt_util.utcnow()
    received_at = data.get(MM_RECEIVED_AT)
    if isinstance(received_at, str) and received_at:
        try:
            timestamp = datetime.fromisoformat(received_at.replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=dt_util.UTC)
        except ValueError:
            _LOGGER.debug("Unparseable received_at %r, using now", received_at)

    return {
        ATTR_BODY: _clean_message_body(body)[:INBOUND_BODY_MAX_LENGTH],
        ATTR_SENDER: str(sender),
        ATTR_TO_NUMBER: str(data.get(MM_TO) or ""),
        ATTR_MESSAGE_SID: str(data.get(MM_MESSAGE_ID) or ""),
        ATTR_TIMESTAMP: timestamp.isoformat(),
        ATTR_PROVIDER: "mobilemessage",
    }


_ENTITY = re.compile(r"&(?:[A-Za-z][A-Za-z0-9]*|#[0-9]+|#[xX][0-9A-Fa-f]+);")
_PHONE = re.compile(r"^\+?[0-9 ()\-]+$")


def _clean_message_body(body: str) -> str:
    """Decode complete HTML entities (&amp; &#39;); the text is otherwise untouched."""
    return _ENTITY.sub(lambda m: html.unescape(m.group(0)), body).strip()


def _normalise_sender(sender: str) -> str:
    """Comparable form: numbers as 61xxxxxxxxx digits, alphanumeric IDs casefolded."""
    sender = sender.strip()
    if not _PHONE.match(sender):
        return sender.casefold()
    digits = re.sub(r"\D", "", sender)
    if digits.startswith("00"):  # 0061...
        digits = digits[2:]
    elif len(digits) == 10 and digits.startswith("0"):  # 04xx...
        digits = "61" + digits[1:]
    return digits


def _should_process_message(entry: ConfigEntry, sender: str) -> bool:
    """Apply the sender allow list, then the block list."""
    sender_n = _normalise_sender(sender)
    allow = {_normalise_sender(n) for n in _option(entry, CONF_SENDER_WHITELIST)}
    if allow and sender_n not in allow:
        return False
    block = {_normalise_sender(n) for n in _option(entry, CONF_SENDER_BLACKLIST)}
    return sender_n not in block


def _check_keywords(keywords: list[str], message_body: str) -> list[str]:
    """Return the keywords (plain or 'regex:' patterns) found in the message."""
    matched = []
    lower = message_body.lower()
    for keyword in keywords:
        if keyword.startswith("regex:"):
            try:
                if re.search(keyword[6:], message_body, re.IGNORECASE):
                    matched.append(keyword)
            except re.error:
                _LOGGER.warning("Invalid keyword regex: %s", keyword[6:])
        elif keyword.lower() in lower:
            matched.append(keyword)
    return matched
