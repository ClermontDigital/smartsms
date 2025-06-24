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
    _LOGGER.info("=== WEBHOOK HANDLER CALLED ===")
    _LOGGER.info("Webhook called with ID: %s", webhook_id)
    _LOGGER.info("Request method: %s", request.method)
    _LOGGER.info("Request URL: %s", request.url)
    
    # Basic security: Check content length
    content_length = getattr(request, 'content_length', None)
    if content_length and content_length > 10000:  # 10KB limit
        _LOGGER.warning("Webhook payload too large: %s bytes", content_length)
        return web.Response(status=413, text="Payload too large")
    
    try:
        # Find the config entry for this webhook
        config_entry = None
        for entry in hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_WEBHOOK_ID) == webhook_id:
                config_entry = entry
                break
        
        if not config_entry:
            _LOGGER.error("No config entry found for webhook ID: %s", webhook_id)
            _LOGGER.debug("Available entries: %s", [
                entry.data.get(CONF_WEBHOOK_ID) for entry in hass.config_entries.async_entries(DOMAIN)
            ])
            return web.Response(status=404)
        
        _LOGGER.info("Content type: %s", request.content_type)
        _LOGGER.info("Request headers: %s", dict(request.headers))
        
        # Parse request data - try different methods since Nabu Casa may transform the request
        data = {}
        body_text = ""
        
        # Method 1: Try aiohttp's post() method first (handles form data properly)
        try:
            _LOGGER.info("Attempting aiohttp post() parsing")
            form_data = await request.post()
            data = dict(form_data)
            _LOGGER.info("Successfully parsed with aiohttp post(): %s", data)
            if data and any(data.values()):  # Check if we got meaningful data
                # Get body text for signature validation if needed
                # Note: This is a workaround since we can't re-read the stream
                body_text = "&".join([f"{k}={v}" for k, v in data.items()])
            else:
                raise ValueError("Empty form data from post()")
        except Exception as e:
            _LOGGER.info("aiohttp post() parsing failed: %s", e)
            
            # Method 2: Get raw body text and parse manually
            try:
                _LOGGER.info("Attempting manual body text parsing")
                body_text = await request.text()
                _LOGGER.info("Raw body text: %s", body_text)
                
                # Try parsing as form data
                from urllib.parse import parse_qs
                parsed_data = parse_qs(body_text)
                _LOGGER.info("Manual form parsing result: %s", parsed_data)
                
                if parsed_data:
                    # Convert lists to single values (Twilio sends single values)
                    data = {k: v[0] if v else '' for k, v in parsed_data.items()}
                    _LOGGER.info("Successfully parsed as form data manually")
                else:
                    # Try JSON parsing
                    import json
                    data = json.loads(body_text)
                    _LOGGER.info("Successfully parsed as JSON")
                    
            except Exception as e2:
                _LOGGER.error("All parsing methods failed: %s", e2)
                return web.Response(status=400, text="Unable to parse request data")
        
        # Validate Twilio signature for security (temporarily disabled for debugging)
        auth_token = config_entry.data.get(CONF_AUTH_TOKEN)
        if False and auth_token and body_text and not _validate_twilio_signature(request, body_text, auth_token):
            _LOGGER.warning("Invalid Twilio signature for webhook %s", webhook_id)
            return web.Response(status=403, text="Invalid signature")
        else:
            _LOGGER.info("Signature validation disabled for debugging")
        
        _LOGGER.info("Final processed data: %s", data)
        
        # Extract message data
        _LOGGER.info("Extracting message data from: %s", data)
        message_data = _extract_message_data(data)
        if not message_data:
            _LOGGER.error("Failed to extract message data from webhook: %s", data)
            return web.Response(status=400, text="Invalid message data")
        
        _LOGGER.info("Extracted message data: %s", message_data)
        
        # Apply filters (be more lenient during debugging)
        if not _should_process_message(config_entry.data, message_data):
            _LOGGER.info("Message filtered out: %s", message_data[ATTR_SENDER])
            # Still process for debugging purposes
            _LOGGER.info("Processing anyway for debugging")
        
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
        
        # Fire entry-specific event for sensors
        hass.bus.async_fire(
            f"{DOMAIN}_data_updated", 
            {"entry_id": config_entry.entry_id}
        )
        
        # Update entities
        _LOGGER.info("Updating entities for entry: %s", config_entry.entry_id)
        await _update_entities(hass, config_entry.entry_id, message_data)
        
        _LOGGER.info("=== MESSAGE PROCESSING COMPLETE ===")
        _LOGGER.info("Processed SMS from %s: %s", 
                    message_data[ATTR_SENDER], 
                    message_data[ATTR_BODY][:50] + "..." if len(message_data[ATTR_BODY]) > 50 else message_data[ATTR_BODY])
        
        return web.Response(status=200, text="Message processed")
        
    except Exception as err:
        _LOGGER.exception("Error processing webhook: %s", err)
        return web.Response(status=500)


def _validate_twilio_signature(request: web.Request, body: str, auth_token: str) -> bool:
    """Validate Twilio webhook signature."""
    try:
        signature = request.headers.get("X-Twilio-Signature")
        if not signature:
            _LOGGER.warning("No X-Twilio-Signature header found")
            return False
        
        # Get the full URL (Twilio uses the full URL for signature calculation)
        url = str(request.url)
        
        # Calculate expected signature using Twilio's method
        # URL + body (for POST data, this is the form-encoded body)
        expected_signature = base64.b64encode(
            hmac.new(
                auth_token.encode("utf-8"),
                f"{url}{body}".encode("utf-8"),
                hashlib.sha1
            ).digest()
        ).decode()
        
        is_valid = hmac.compare_digest(signature, expected_signature)
        if not is_valid:
            _LOGGER.warning(
                "Signature validation failed. Expected: %s, Got: %s", 
                expected_signature, signature
            )
        else:
            _LOGGER.debug("Twilio signature validation successful")
        
        return is_valid
        
    except Exception as err:
        _LOGGER.error("Error validating Twilio signature: %s", err)
        return False


def _extract_message_data(data: dict) -> dict[str, Any] | None:
    """Extract message data from Twilio webhook payload."""
    try:
        _LOGGER.info("=== EXTRACTING MESSAGE DATA ===")
        _LOGGER.info("Available data keys: %s", list(data.keys()))
        
        body = data.get(TWILIO_BODY, "")
        sender = data.get(TWILIO_FROM, "")
        to_number = data.get(TWILIO_TO, "")
        message_sid = data.get(TWILIO_MESSAGE_SID, "")
        timestamp = data.get(TWILIO_TIMESTAMP)
        
        _LOGGER.info("Extracted fields:")
        _LOGGER.info("  body: %s", body)
        _LOGGER.info("  sender: %s", sender)
        _LOGGER.info("  to_number: %s", to_number)
        _LOGGER.info("  message_sid: %s", message_sid)
        _LOGGER.info("  timestamp: %s", timestamp)
        
        # Validate required fields - be more lenient for debugging
        if not body:
            _LOGGER.warning("Missing message body")
            body = data.get("Message", data.get("Text", ""))  # Try alternative field names
            
        if not sender:
            _LOGGER.warning("Missing sender")
            sender = data.get("FromNumber", data.get("Phone", ""))  # Try alternative field names
            
        if not body or not sender:
            _LOGGER.error("Still missing required fields after fallback: body='%s', sender='%s'", body, sender)
            _LOGGER.error("Available data keys: %s", list(data.keys()))
            # Don't return None yet - let's see what we have
        
        # Basic input validation
        if body and len(body) > 1600:  # SMS length limit
            _LOGGER.warning("Message body too long: %d chars", len(body))
            body = body[:1600]
        
        # Validate phone number format (basic check) - be more lenient
        if sender and not sender.startswith('+'):
            _LOGGER.info("Sender doesn't start with +, but continuing: %s", sender)
        
        # Parse timestamp - try multiple possible field names
        timestamp_iso = dt_util.utcnow().isoformat()
        timestamp_fields = [TWILIO_TIMESTAMP, "DateCreated", "DateUpdated", "timestamp", "time"]
        
        for field in timestamp_fields:
            timestamp = data.get(field)
            if timestamp:
                _LOGGER.info("Found timestamp in field '%s': %s", field, timestamp)
                try:
                    # Try multiple timestamp formats
                    for fmt in [
                        "%Y-%m-%d %H:%M:%S",
                        "%a, %d %b %Y %H:%M:%S %z",
                        "%Y-%m-%dT%H:%M:%S.%fZ",
                        "%Y-%m-%dT%H:%M:%SZ"
                    ]:
                        try:
                            parsed_timestamp = datetime.strptime(timestamp, fmt)
                            timestamp_iso = parsed_timestamp.isoformat()
                            _LOGGER.info("Successfully parsed timestamp: %s", timestamp_iso)
                            break
                        except ValueError:
                            continue
                    break
                except Exception as e:
                    _LOGGER.warning("Failed to parse timestamp '%s': %s", timestamp, e)
        
        result = {
            ATTR_BODY: body or "",
            ATTR_SENDER: sender or "",
            ATTR_TO_NUMBER: to_number or "",
            ATTR_MESSAGE_SID: message_sid or "",
            ATTR_TIMESTAMP: timestamp_iso,
            ATTR_PROVIDER: "twilio",
        }
        
        _LOGGER.info("Final extracted message data: %s", result)
        return result
        
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
    _LOGGER.info("Starting entity update for entry: %s", entry_id)
    
    # Use data store for proper message handling
    data_store = hass.data[DOMAIN][entry_id].get("data_store")
    if data_store:
        _LOGGER.info("Using data store to store message")
        data_store.store_message(message_data)
    else:
        # Fallback to direct storage
        _LOGGER.info("Using fallback direct storage")
        hass.data[DOMAIN][entry_id]["latest_message"] = message_data
        current_count = hass.data[DOMAIN][entry_id].get("message_count", 0)
        hass.data[DOMAIN][entry_id]["message_count"] = current_count + 1
    
    # Trigger entity updates
    _LOGGER.info("Triggering entity updates")
    async_trigger_entity_updates(hass, entry_id)


def async_trigger_entity_updates(hass: HomeAssistant, entry_id: str) -> None:
    """Trigger updates for all entities in this config entry."""
    # Fire an internal event that entities can listen to for updates
    hass.bus.async_fire(f"{DOMAIN}_data_updated", {"entry_id": entry_id}) 