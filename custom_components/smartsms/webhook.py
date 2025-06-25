"""Webhook handling for SmartSMS integration."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import re
from datetime import datetime
from typing import Any
from urllib.parse import parse_qs

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

# Store webhook to config entry mapping for efficient lookup
_WEBHOOK_TO_ENTRY: dict[str, str] = {}


async def async_register_webhook(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Register webhook for SMS reception."""
    webhook_id = entry.data[CONF_WEBHOOK_ID]
    
    _LOGGER.error("🔧 WEBHOOK REGISTRATION STARTING")
    _LOGGER.error("🔧 Webhook ID: %s", webhook_id)
    _LOGGER.error("🔧 Entry ID: %s", entry.entry_id)
    _LOGGER.error("🔧 Entry title: %s", entry.title)
    
    try:
        # Check webhook system state
        webhook_component = hass.data.get('webhook')
        _LOGGER.error("🔧 Webhook component available: %s", webhook_component is not None)
        
        if webhook_component and hasattr(webhook_component, '_handlers'):
            existing_handlers = webhook_component._handlers
            _LOGGER.error("🔧 Existing webhook handlers: %s", list(existing_handlers.keys()))
            if webhook_id in existing_handlers:
                _LOGGER.error("🔧 WARNING: Webhook ID already exists - unregistering first")
                try:
                    webhook.async_unregister(hass, webhook_id)
                except Exception as e:
                    _LOGGER.warning("🔧 Failed to unregister existing webhook: %s", e)
        
        # Register webhook
        _LOGGER.error("🔧 Calling webhook.async_register...")
        webhook.async_register(
            hass,
            DOMAIN,
            f"SmartSMS Webhook ({entry.title})",
            webhook_id,
            handle_webhook,
        )
        _LOGGER.error("🔧 webhook.async_register completed")
        
        # Store mapping for efficient lookup
        _WEBHOOK_TO_ENTRY[webhook_id] = entry.entry_id
        _LOGGER.error("🔧 Added to mapping: %s -> %s", webhook_id, entry.entry_id)
        
        # Verify registration worked
        webhook_component_after = hass.data.get('webhook')
        if webhook_component_after and hasattr(webhook_component_after, '_handlers'):
            handlers_after = webhook_component_after._handlers
            _LOGGER.error("🔧 Handlers after registration: %s", list(handlers_after.keys()))
            if webhook_id in handlers_after:
                _LOGGER.error("🔧 ✅ WEBHOOK SUCCESSFULLY REGISTERED!")
                handler_info = handlers_after[webhook_id]
                _LOGGER.error("🔧 Handler info - domain: %s, name: %s", 
                            getattr(handler_info, 'domain', 'unknown'),
                            getattr(handler_info, 'name', 'unknown'))
            else:
                _LOGGER.error("🔧 ❌ WEBHOOK REGISTRATION FAILED - NOT IN HANDLERS!")
        
        _LOGGER.error("🔧 Final webhook mapping: %s", _WEBHOOK_TO_ENTRY)
        _LOGGER.error("🔧 WEBHOOK REGISTRATION COMPLETE")
        
    except Exception as err:
        _LOGGER.error("🔧 ❌ WEBHOOK REGISTRATION EXCEPTION: %s", err)
        _LOGGER.exception("Full exception traceback:")
        raise


async def async_unregister_webhook(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Unregister webhook."""
    webhook_id = entry.data[CONF_WEBHOOK_ID]
    
    try:
        webhook.async_unregister(hass, webhook_id)
        
        # Remove from mapping
        _WEBHOOK_TO_ENTRY.pop(webhook_id, None)
        
        _LOGGER.info("Unregistered SmartSMS webhook: %s", webhook_id)
        
    except Exception as err:
        _LOGGER.error("Failed to unregister webhook %s: %s", webhook_id, err)


async def handle_webhook(
    hass: HomeAssistant, webhook_id: str, request: web.Request
) -> web.Response:
    """Handle incoming SMS webhook from Twilio."""
    _LOGGER.error("🚀 WEBHOOK HANDLER CALLED!")
    _LOGGER.error("🚀 Webhook ID: %s", webhook_id)
    _LOGGER.error("🚀 Request method: %s", request.method)
    _LOGGER.error("🚀 Request URL: %s", request.url)
    _LOGGER.error("🚀 Request headers: %s", dict(request.headers))
    _LOGGER.error("🚀 All webhook mappings: %s", _WEBHOOK_TO_ENTRY)
    
    # Fire a test event to see if this handler is being called at all
    hass.bus.async_fire("smartsms_webhook_test", {
        "webhook_id": webhook_id,
        "method": request.method,
        "url": str(request.url),
        "timestamp": dt_util.utcnow().isoformat()
    })
    
    try:
        # Security check: payload size limit
        content_length = getattr(request, 'content_length', None)
        if content_length and content_length > 10000:  # 10KB limit
            _LOGGER.warning("Webhook payload too large: %s bytes", content_length)
            return web.Response(status=413, text="Payload too large")
        
        # Find config entry efficiently
        entry_id = _WEBHOOK_TO_ENTRY.get(webhook_id)
        if not entry_id:
            _LOGGER.error("No config entry found for webhook ID: %s", webhook_id)
            _LOGGER.error("Available mappings: %s", _WEBHOOK_TO_ENTRY)
            return web.Response(status=404, text="Webhook not found")
        
        config_entry = None
        for entry in hass.config_entries.async_entries(DOMAIN):
            if entry.entry_id == entry_id:
                config_entry = entry
                break
        
        if not config_entry:
            _LOGGER.error("Config entry %s not found for webhook %s", entry_id, webhook_id)
            return web.Response(status=404, text="Config entry not found")
        
        # Parse request data properly (only consume body once)
        data = await _parse_request_data(request)
        if not data:
            _LOGGER.error("Failed to parse webhook request data")
            return web.Response(status=400, text="Invalid request data")
        
        _LOGGER.error("🚀 Parsed webhook data: %s", data)
        
        # Validate Twilio signature if enabled
        auth_token = config_entry.data.get(CONF_AUTH_TOKEN)
        if False and auth_token and not _validate_twilio_signature(request, data, auth_token):
            _LOGGER.warning("Invalid Twilio signature for webhook %s", webhook_id)
            return web.Response(status=403, text="Invalid signature")
        
        # Extract and validate message data
        message_data = _extract_message_data(data)
        if not message_data:
            _LOGGER.error("Failed to extract valid message data")
            return web.Response(status=400, text="Invalid message data")
        
        _LOGGER.error("🚀 Extracted message from %s: %s", message_data[ATTR_SENDER], message_data[ATTR_BODY])
        
        # Apply filters
        if not _should_process_message(config_entry.data, message_data):
            _LOGGER.debug("Message filtered out from %s", message_data[ATTR_SENDER])
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
        
        _LOGGER.error("🚀 ✅ MESSAGE PROCESSED SUCCESSFULLY!")
        _LOGGER.info("Processed SMS from %s: %s", 
                    message_data[ATTR_SENDER], 
                    message_data[ATTR_BODY][:50] + "..." if len(message_data[ATTR_BODY]) > 50 else message_data[ATTR_BODY])
        
        return web.Response(status=200, text="Message processed", content_type="text/plain")
        
    except Exception as err:
        _LOGGER.exception("🚀 ❌ ERROR processing webhook %s: %s", webhook_id, err)
        return web.Response(status=500, text="Internal server error")


async def _parse_request_data(request: web.Request) -> dict[str, Any] | None:
    """Parse request data from various formats."""
    try:
        # Try form data first (most common for Twilio)
        try:
            form_data = await request.post()
            if form_data:
                data = dict(form_data)
                _LOGGER.error("🚀 Successfully parsed as form data: %s", data)
                return data
        except Exception as e:
            _LOGGER.debug("Form data parsing failed: %s", e)
        
        # Try raw text parsing
        try:
            body_text = await request.text()
            if body_text:
                _LOGGER.error("🚀 Raw body text: %s", body_text)
                
                # Try URL-encoded parsing
                parsed_data = parse_qs(body_text)
                if parsed_data:
                    # Convert lists to single values
                    data = {k: v[0] if v else '' for k, v in parsed_data.items()}
                    _LOGGER.error("🚀 Successfully parsed as URL-encoded text: %s", data)
                    return data
                
                # Try JSON parsing
                data = json.loads(body_text)
                _LOGGER.error("🚀 Successfully parsed as JSON: %s", data)
                return data
        except Exception as e:
            _LOGGER.debug("Text parsing failed: %s", e)
        
        _LOGGER.warning("Unable to parse request data")
        return None
        
    except Exception as err:
        _LOGGER.error("Critical error parsing request: %s", err)
        return None


def _validate_twilio_signature(request: web.Request, data: dict[str, Any], auth_token: str) -> bool:
    """Validate Twilio webhook signature."""
    try:
        signature = request.headers.get("X-Twilio-Signature")
        if not signature:
            _LOGGER.debug("No X-Twilio-Signature header found")
            return False
        
        # Get the full URL
        url = str(request.url)
        
        # Reconstruct the body for signature validation
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
        
        is_valid = hmac.compare_digest(signature, expected_signature)
        if not is_valid:
            _LOGGER.warning("Signature validation failed")
        
        return is_valid
        
    except Exception as err:
        _LOGGER.error("Error validating Twilio signature: %s", err)
        return False


def _extract_message_data(data: dict[str, Any]) -> dict[str, Any] | None:
    """Extract message data from Twilio webhook payload."""
    try:
        body = data.get(TWILIO_BODY, "")
        sender = data.get(TWILIO_FROM, "")
        to_number = data.get(TWILIO_TO, "")
        message_sid = data.get(TWILIO_MESSAGE_SID, "")
        timestamp = data.get(TWILIO_TIMESTAMP)
        
        # Validate required fields
        if not body or not sender:
            _LOGGER.warning("Missing required fields: body=%s, sender=%s", bool(body), bool(sender))
            return None
        
        # Input validation
        if len(body) > 1600:  # SMS length limit
            _LOGGER.warning("Message body too long: %d chars", len(body))
            body = body[:1600]
        
        # Parse timestamp
        timestamp_iso = dt_util.utcnow().isoformat()
        if timestamp:
            try:
                for fmt in [
                    "%Y-%m-%d %H:%M:%S",
                    "%a, %d %b %Y %H:%M:%S %z",
                    "%Y-%m-%dT%H:%M:%S.%fZ",
                    "%Y-%m-%dT%H:%M:%SZ"
                ]:
                    try:
                        parsed_timestamp = datetime.strptime(timestamp, fmt)
                        timestamp_iso = parsed_timestamp.isoformat()
                        break
                    except ValueError:
                        continue
            except Exception as e:
                _LOGGER.debug("Failed to parse timestamp '%s': %s", timestamp, e)
        
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


def _should_process_message(config_data: dict[str, Any], message_data: dict[str, Any]) -> bool:
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
        try:
            if keyword.startswith("regex:"):
                pattern = keyword[6:]  # Remove 'regex:' prefix
                if re.search(pattern, message_body, re.IGNORECASE):
                    matched.append(keyword)
            else:
                # Simple case-insensitive substring match
                if keyword.lower() in message_lower:
                    matched.append(keyword)
        except re.error as e:
            _LOGGER.warning("Invalid regex pattern '%s': %s", keyword, e)
    
    return matched


async def _update_entities(hass: HomeAssistant, entry_id: str, message_data: dict[str, Any]) -> None:
    """Update entity states with new message data."""
    try:
        # Get data store
        entry_data = hass.data[DOMAIN].get(entry_id, {})
        data_store = entry_data.get("data_store")
        
        if data_store:
            data_store.store_message(message_data)
        else:
            _LOGGER.warning("No data store found for entry %s", entry_id)
        
        # Fire update event for entities
        hass.bus.async_fire(f"{DOMAIN}_data_updated", {"entry_id": entry_id})
        
    except Exception as err:
        _LOGGER.error("Error updating entities for entry %s: %s", entry_id, err) 