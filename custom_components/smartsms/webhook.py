"""Webhook handling for SmartSMS integration."""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import re
from datetime import datetime
from typing import Any

from aiohttp import web
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.components import webhook
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_BODY,
    ATTR_MATCHED_KEYWORDS,
    ATTR_MESSAGE_SID,
    ATTR_PROVIDER,
    ATTR_SENDER,
    ATTR_TIMESTAMP,
    ATTR_TO_NUMBER,
    BINARY_SENSOR_RESET_DELAY,
    CONF_AUTH_TOKEN,
    CONF_KEYWORDS,
    CONF_SENDER_BLACKLIST,
    CONF_SENDER_WHITELIST,
    CONF_WEBHOOK_ID,
    DOMAIN,
    EVENT_KEYWORD_MATCHED,
    EVENT_MESSAGE_RECEIVED,
    TWILIO_ACCOUNT_SID,
    TWILIO_BODY,
    TWILIO_FROM,
    TWILIO_MESSAGE_SID,
    TWILIO_TIMESTAMP,
    TWILIO_TO,
)

_LOGGER = logging.getLogger(__name__)


async def async_register_webhook(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Register webhook for SMS reception."""
    webhook_id = entry.data[CONF_WEBHOOK_ID]
    
    webhook.async_register(
        hass,
        DOMAIN,
        f"SmartSMS Webhook ({entry.title})",
        webhook_id,
        handle_webhook,
    )
    
    _LOGGER.info("Registered SmartSMS webhook: %s", webhook_id)


async def async_unregister_webhook(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Unregister webhook."""
    webhook_id = entry.data[CONF_WEBHOOK_ID]
    webhook.async_unregister(hass, webhook_id)
    _LOGGER.info("Unregistered SmartSMS webhook: %s", webhook_id)


async def handle_webhook(
    hass: HomeAssistant, webhook_id: str, request: web.Request
) -> web.Response:
    """Handle incoming SMS webhook from Twilio."""
    try:
        # Find the config entry for this webhook
        config_entry = None
        for entry in hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_WEBHOOK_ID) == webhook_id:
                config_entry = entry
                break
        
        if not config_entry:
            _LOGGER.error("No config entry found for webhook ID: %s", webhook_id)
            return web.Response(status=404)
        
        # Get request data
        if request.content_type == "application/x-www-form-urlencoded":
            data = await request.post()
        else:
            data = await request.json()
        
        _LOGGER.debug("Received webhook data: %s", data)
        
        # Validate Twilio signature if auth token is available
        auth_token = config_entry.data.get(CONF_AUTH_TOKEN)
        if auth_token and not _validate_twilio_signature(request, data, auth_token):
            _LOGGER.warning("Invalid Twilio signature for webhook %s", webhook_id)
            return web.Response(status=403)
        
        # Extract message data
        message_data = _extract_message_data(data)
        if not message_data:
            _LOGGER.error("Failed to extract message data from webhook")
            return web.Response(status=400)
        
        # Apply filters
        if not _should_process_message(config_entry.data, message_data):
            _LOGGER.debug("Message filtered out: %s", message_data[ATTR_SENDER])
            return web.Response(status=200, text="Message filtered")
        
        # Check for keyword matches
        matched_keywords = _check_keywords(
            config_entry.data.get(CONF_KEYWORDS, []),
            message_data[ATTR_BODY]
        )
        if matched_keywords:
            message_data[ATTR_MATCHED_KEYWORDS] = matched_keywords
        
        # Fire events
        hass.bus.async_fire(EVENT_MESSAGE_RECEIVED, message_data)
        
        if matched_keywords:
            hass.bus.async_fire(EVENT_KEYWORD_MATCHED, message_data)
        
        # Update entities
        await _update_entities(hass, config_entry.entry_id, message_data)
        
        _LOGGER.info("Processed SMS from %s: %s", 
                    message_data[ATTR_SENDER], 
                    message_data[ATTR_BODY][:50] + "..." if len(message_data[ATTR_BODY]) > 50 else message_data[ATTR_BODY])
        
        return web.Response(status=200, text="Message processed")
        
    except Exception as err:
        _LOGGER.exception("Error processing webhook: %s", err)
        return web.Response(status=500)


def _validate_twilio_signature(request: web.Request, data: dict, auth_token: str) -> bool:
    """Validate Twilio webhook signature."""
    try:
        signature = request.headers.get("X-Twilio-Signature")
        if not signature:
            return False
        
        # Build the URL (Twilio uses the full URL for signature calculation)
        url = str(request.url)
        
        # Sort form data for signature calculation
        sorted_data = sorted(data.items())
        body = "&".join([f"{k}={v}" for k, v in sorted_data])
        
        # Calculate expected signature
        expected_signature = base64.b64encode(
            hmac.new(
                auth_token.encode("utf-8"),
                f"{url}{body}".encode("utf-8"),
                hashlib.sha1
            ).digest()
        ).decode()
        
        return hmac.compare_digest(signature, expected_signature)
        
    except Exception as err:
        _LOGGER.error("Error validating Twilio signature: %s", err)
        return False


def _extract_message_data(data: dict) -> dict[str, Any] | None:
    """Extract message data from Twilio webhook payload."""
    try:
        body = data.get(TWILIO_BODY, "")
        sender = data.get(TWILIO_FROM, "")
        to_number = data.get(TWILIO_TO, "")
        message_sid = data.get(TWILIO_MESSAGE_SID, "")
        timestamp = data.get(TWILIO_TIMESTAMP)
        
        if not body or not sender:
            return None
        
        # Parse timestamp or use current time
        if timestamp:
            try:
                parsed_timestamp = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
                timestamp_iso = parsed_timestamp.isoformat()
            except ValueError:
                timestamp_iso = dt_util.utcnow().isoformat()
        else:
            timestamp_iso = dt_util.utcnow().isoformat()
        
        return {
            ATTR_BODY: body,
            ATTR_SENDER: sender,
            ATTR_TO_NUMBER: to_number,
            ATTR_MESSAGE_SID: message_sid,
            ATTR_TIMESTAMP: timestamp_iso,
            ATTR_PROVIDER: "twilio",
        }
        
    except Exception as err:
        _LOGGER.error("Error extracting message data: %s", err)
        return None


def _should_process_message(config_data: dict, message_data: dict) -> bool:
    """Check if message should be processed based on filters."""
    sender = message_data[ATTR_SENDER]
    
    # Check whitelist
    whitelist = config_data.get(CONF_SENDER_WHITELIST, [])
    if whitelist and sender not in whitelist:
        return False
    
    # Check blacklist
    blacklist = config_data.get(CONF_SENDER_BLACKLIST, [])
    if blacklist and sender in blacklist:
        return False
    
    return True


def _check_keywords(keywords: list[str], message_body: str) -> list[str]:
    """Check if message contains any keywords and return matches."""
    if not keywords:
        return []
    
    matched = []
    message_lower = message_body.lower()
    
    for keyword in keywords:
        # Support regex patterns if they start with 'regex:'
        if keyword.startswith("regex:"):
            pattern = keyword[6:]  # Remove 'regex:' prefix
            try:
                if re.search(pattern, message_body, re.IGNORECASE):
                    matched.append(keyword)
            except re.error:
                _LOGGER.warning("Invalid regex pattern: %s", pattern)
        else:
            # Simple case-insensitive substring match
            if keyword.lower() in message_lower:
                matched.append(keyword)
    
    return matched


async def _update_entities(hass: HomeAssistant, entry_id: str, message_data: dict) -> None:
    """Update entity states with new message data."""
    # Store message data for entities to access
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}
    
    if entry_id not in hass.data[DOMAIN]:
        hass.data[DOMAIN][entry_id] = {}
    
    # Store the latest message data
    hass.data[DOMAIN][entry_id]["latest_message"] = message_data
    
    # Increment message count
    current_count = hass.data[DOMAIN][entry_id].get("message_count", 0)
    hass.data[DOMAIN][entry_id]["message_count"] = current_count + 1
    
    # Trigger entity updates
    async_trigger_entity_updates(hass, entry_id)


def async_trigger_entity_updates(hass: HomeAssistant, entry_id: str) -> None:
    """Trigger updates for all entities in this config entry."""
    # Fire an internal event that entities can listen to for updates
    hass.bus.async_fire(f"{DOMAIN}_data_updated", {"entry_id": entry_id}) 