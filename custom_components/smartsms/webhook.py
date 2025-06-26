"""Webhook handling for SmartSMS integration."""
from __future__ import annotations

import base64
import hashlib
import hmac
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
    CONF_API_PASSWORD,
    CONF_KEYWORDS,
    CONF_SENDER_BLACKLIST,
    CONF_SENDER_WHITELIST,
    CONF_WEBHOOK_ID,
    DOMAIN,
    EVENT_KEYWORD_MATCHED,
    EVENT_MESSAGE_RECEIVED,
    MM_MESSAGE,
    MM_MESSAGE_ID,
    MM_RECEIVED_AT,
    MM_SENDER,
    MM_TO,
)

_LOGGER = logging.getLogger(__name__)

# Global webhook mapping for efficient lookup
_WEBHOOK_TO_ENTRY: dict[str, str] = {}


async def async_register_webhook(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Register webhook for SMS reception."""
    webhook_id = entry.data[CONF_WEBHOOK_ID]
    
    try:
        # Check if webhook already exists
        try:
            webhook.async_unregister(hass, webhook_id)
        except ValueError:
            # Webhook doesn't exist, which is fine
            pass
        
        # Register the webhook
        webhook.async_register(
            hass,
            DOMAIN,
            f"SmartSMS ({entry.title})",
            webhook_id,
            handle_webhook,
        )
        
        # Store mapping for efficient lookup
        _WEBHOOK_TO_ENTRY[webhook_id] = entry.entry_id
        
        _LOGGER.info("Registered SmartSMS webhook: %s", webhook_id)
        
    except Exception as err:
        _LOGGER.error("Failed to register webhook %s: %s", webhook_id, err)
        raise


async def async_unregister_webhook(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Unregister webhook."""
    webhook_id = entry.data[CONF_WEBHOOK_ID]
    
    try:
        webhook.async_unregister(hass, webhook_id)
        _WEBHOOK_TO_ENTRY.pop(webhook_id, None)
        _LOGGER.info("Unregistered SmartSMS webhook: %s", webhook_id)
        
    except Exception as err:
        _LOGGER.error("Failed to unregister webhook %s: %s", webhook_id, err)


async def handle_webhook(
    hass: HomeAssistant, webhook_id: str, request: web.Request
) -> web.Response:
    """Handle incoming SMS webhook from Twilio."""
    _LOGGER.debug("SmartSMS webhook called: %s", webhook_id)
    
    try:
        # Security: Check payload size
        content_length = request.headers.get('content-length')
        if content_length and int(content_length) > 10000:
            _LOGGER.warning("Webhook payload too large: %s bytes", content_length)
            return web.Response(status=413, text="PAYLOAD_TOO_LARGE", content_type="text/plain")
        
        # Find config entry
        entry_id = _WEBHOOK_TO_ENTRY.get(webhook_id)
        if not entry_id:
            _LOGGER.error("No config entry found for webhook ID: %s", webhook_id)
            return web.Response(status=404, text="WEBHOOK_NOT_FOUND", content_type="text/plain")
        
        # Get config entry
        config_entry = None
        for entry in hass.config_entries.async_entries(DOMAIN):
            if entry.entry_id == entry_id:
                config_entry = entry
                break
        
        if not config_entry:
            _LOGGER.error("Config entry %s not found", entry_id)
            return web.Response(status=404, text="CONFIG_NOT_FOUND", content_type="text/plain")
        
        # Parse request data
        data = await _parse_request_data(request)
        if not data:
            _LOGGER.error("Failed to parse webhook request data")
            return web.Response(status=400, text="INVALID_DATA", content_type="text/plain")
        
        # Note: Mobile Message uses webhook URLs for security rather than signature validation
        # The webhook URL itself acts as the authentication mechanism
        
        # Extract message data
        message_data = _extract_message_data(data)
        if not message_data:
            _LOGGER.error("Failed to extract valid message data")
            return web.Response(status=400, text="INVALID_MESSAGE", content_type="text/plain")
        
        # Apply filters
        if not _should_process_message(config_entry.data, message_data):
            _LOGGER.debug("Message filtered out from %s", message_data[ATTR_SENDER])
            return web.Response(status=200, text="FILTERED", content_type="text/plain")
        
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
        
        _LOGGER.info(
            "Processed SMS from %s: %s", 
            message_data[ATTR_SENDER], 
            message_data[ATTR_BODY][:50] + "..." if len(message_data[ATTR_BODY]) > 50 else message_data[ATTR_BODY]
        )
        
        # Return simple OK response that Mobile Message expects
        return web.Response(status=200, text="OK", content_type="text/plain")
        
    except Exception as err:
        _LOGGER.exception("Error processing webhook %s: %s", webhook_id, err)
        return web.Response(status=500, text="ERROR", content_type="text/plain")


async def _parse_request_data(request: web.Request) -> dict[str, Any] | None:
    """Parse request data from Mobile Message webhook (JSON format)."""
    try:
        _LOGGER.debug("Request object type: %s", type(request))
        _LOGGER.debug("Request headers: %s", dict(request.headers) if hasattr(request, 'headers') else 'No headers')
        _LOGGER.debug("Request content type: %s", getattr(request, 'content_type', 'Unknown'))
        
        # Handle different request types safely
        body = b''
        body_str = ''
        
        # Try to read body - handle different request object types
        if hasattr(request, 'read'):
            try:
                body = await request.read()
                _LOGGER.debug("Read body bytes: %d", len(body))
            except Exception as e:
                _LOGGER.error("Failed to read request body: %s", e)
                return None
        elif hasattr(request, 'text'):
            try:
                body_str = await request.text()
                _LOGGER.debug("Got body text directly: %d chars", len(body_str))
            except Exception as e:
                _LOGGER.error("Failed to get request text: %s", e)
                return None
        elif hasattr(request, 'json'):
            try:
                # Direct JSON parsing if available
                return await request.json()
            except Exception as e:
                _LOGGER.error("Failed to parse JSON directly: %s", e)
                return None
        else:
            _LOGGER.error("Request object has no readable methods: %s", dir(request))
            return None
        
        # Convert bytes to string if we got bytes
        if body and not body_str:
            try:
                body_str = body.decode('utf-8')
            except UnicodeDecodeError:
                try:
                    body_str = body.decode('latin-1')
                    _LOGGER.warning("Using latin-1 encoding for webhook data")
                except UnicodeDecodeError:
                    body_str = body.decode('utf-8', errors='replace')
                    _LOGGER.warning("Using UTF-8 with error replacement for webhook data")
        
        _LOGGER.debug("Body string: %s", body_str[:500] if body_str else 'Empty')
        
        if not body_str:
            _LOGGER.error("Empty request body")
            return None
        
        # Mobile Message sends JSON data
        content_type = getattr(request, 'content_type', '').lower()
        if 'json' in content_type or content_type == 'application/json':
            import json
            return json.loads(body_str)
        
        # Fallback: try to parse as JSON anyway (some providers don't set content-type correctly)
        try:
            import json
            return json.loads(body_str)
        except json.JSONDecodeError:
            _LOGGER.error("Failed to parse webhook data as JSON: %s", body_str[:200])
            return None
        
    except Exception as err:
        _LOGGER.exception("Error parsing request data: %s", err)
        return None


# Mobile Message doesn't use signature validation - webhook URL security is sufficient


def _extract_message_data(data: dict[str, Any]) -> dict[str, Any] | None:
    """Extract SMS message data from Mobile Message webhook payload."""
    try:
        # Extract Mobile Message fields (direct JSON access, no form parsing needed)
        body = data.get(MM_MESSAGE, "")
        sender = data.get(MM_SENDER, "")
        to_number = data.get(MM_TO, "")
        message_id = data.get(MM_MESSAGE_ID, "")
        received_at_str = data.get(MM_RECEIVED_AT, "")
        
        # Debug log the raw extracted values
        _LOGGER.debug("RAW EXTRACTED - Message: %r, Sender: %r, To: %r", body, sender, to_number)
        
        if not body or not sender:
            _LOGGER.error("Missing required fields: Message=%s, Sender=%s", body, sender)
            return None
        
        # Parse timestamp (Mobile Message uses ISO format)
        if received_at_str:
            try:
                # Parse ISO timestamp format: "2024-01-15T10:30:45Z"
                timestamp = datetime.fromisoformat(received_at_str.replace('Z', '+00:00'))
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=dt_util.UTC)
            except ValueError as e:
                _LOGGER.warning("Failed to parse timestamp '%s': %s", received_at_str, e)
                timestamp = dt_util.utcnow()
        else:
            timestamp = dt_util.utcnow()
        
        # Validate phone numbers (Mobile Message uses international format)
        if not _is_valid_phone(sender) or not _is_valid_phone(to_number):
            _LOGGER.warning("Invalid phone number format: Sender=%s, To=%s", sender, to_number)
        
        # Clean up the message body to remove problematic characters
        clean_body = _clean_message_body(body)
        
        return {
            ATTR_BODY: clean_body[:1000],  # Limit message length
            ATTR_SENDER: sender,
            ATTR_TO_NUMBER: to_number,
            ATTR_MESSAGE_SID: message_id,
            ATTR_TIMESTAMP: timestamp.isoformat(),
            ATTR_PROVIDER: "mobilemessage",
        }
        
    except Exception as err:
        _LOGGER.error("Error extracting message data: %s", err)
        return None


def _is_valid_phone(phone: str) -> bool:
    """Validate phone number format (Australian and international)."""
    if not phone:
        return False
    
    # Mobile Message supports both Australian local and international formats
    # Australian international: +61412345678
    # Australian local: 0412345678  
    # Other international: +1234567890
    
    # Check for international format (+country code + number)
    if phone.startswith('+'):
        return bool(re.match(r'^\+[1-9]\d{7,15}$', phone))
    
    # Check for Australian local format (0xxxxxxxxx)
    if phone.startswith('0'):
        return bool(re.match(r'^0[2-9]\d{8}$', phone))
    
    # Allow basic numeric format for flexibility
    return bool(re.match(r'^[1-9]\d{7,15}$', phone))


def _should_process_message(config: dict[str, Any], message_data: dict[str, Any]) -> bool:
    """Check if message should be processed based on filters."""
    sender = message_data[ATTR_SENDER]
    body = message_data[ATTR_BODY]
    
    # Whitelist check (if configured, only allow these)
    whitelist = config.get(CONF_SENDER_WHITELIST, [])
    if whitelist and sender not in whitelist:
        return False
    
    # Blacklist check (never allow these)
    blacklist = config.get(CONF_SENDER_BLACKLIST, [])
    if blacklist and sender in blacklist:
        return False
    
    return True


def _clean_message_body(body: str) -> str:
    """Clean SMS message body by keeping ONLY printable ASCII characters."""
    if not body:
        return body
    
    import re
    import html
    
    _LOGGER.debug("ORIGINAL SMS BODY: %r (len=%d)", body, len(body))
    
    # Step 1: Handle URL decoding if needed (defensive)
    try:
        from urllib.parse import unquote_plus
        if '%' in body and re.search(r'%[0-9A-Fa-f]{2}', body):
            body = unquote_plus(body)
            _LOGGER.debug("URL decoded: %r", body)
    except Exception:
        pass
    
    # Step 2: HTML entity decoding
    try:
        body = html.unescape(body)
        _LOGGER.debug("HTML unescaped: %r", body)
    except Exception:
        pass
    
    # Step 3: AGGRESSIVE ASCII-ONLY FILTERING + MARKDOWN REMOVAL
    # Keep only printable ASCII characters (32-126) but exclude markdown chars
    # This removes ALL Unicode, control chars, invisible characters AND markdown
    ascii_chars = []
    for char in body:
        char_code = ord(char)
        if 32 <= char_code <= 126:  # Printable ASCII range
            # But specifically remove asterisks and other markdown characters
            if char not in ['*', '_', '`', '#', '[', ']', '!', '|', '\\', '^', '>', '<', '~']:
                ascii_chars.append(char)
            else:
                _LOGGER.debug("WEBHOOK REMOVED markdown char: %r (code=%d)", char, char_code)
        elif char_code == 9:  # Tab -> space
            ascii_chars.append(' ')
        elif char_code in (10, 13):  # LF, CR -> space
            ascii_chars.append(' ')
        else:
            # Log what we're removing for debugging
            _LOGGER.debug("WEBHOOK REMOVED non-ASCII char: %r (code=%d)", char, char_code)
    
    clean_body = ''.join(ascii_chars)
    _LOGGER.debug("ASCII-only result: %r", clean_body)
    
    # Step 4: Normalize whitespace
    clean_body = re.sub(r'\s+', ' ', clean_body)
    clean_body = clean_body.strip()
    
    _LOGGER.debug("FINAL CLEANED: %r (len=%d)", clean_body, len(clean_body))
    
    return clean_body


def _check_keywords(keywords: list[str], message_body: str) -> list[str]:
    """Check for keyword matches in message body."""
    matched = []
    message_lower = message_body.lower()
    
    for keyword in keywords:
        if keyword.startswith("regex:"):
            # Regex pattern matching
            pattern = keyword[6:]  # Remove 'regex:' prefix
            try:
                if re.search(pattern, message_body, re.IGNORECASE):
                    matched.append(keyword)
            except re.error:
                _LOGGER.warning("Invalid regex pattern: %s", pattern)
        else:
            # Simple keyword matching
            if keyword.lower() in message_lower:
                matched.append(keyword)
    
    return matched


async def _update_entities(hass: HomeAssistant, entry_id: str, message_data: dict[str, Any]) -> None:
    """Update entity states with new message data."""
    try:
        # Get data store
        entry_data = hass.data[DOMAIN].get(entry_id, {})
        data_store = entry_data.get("data_store")
        
        if data_store:
            data_store.store_message(message_data)
        
        # Fire update event for entities
        hass.bus.async_fire(f"{DOMAIN}_data_updated", {"entry_id": entry_id})
        
    except Exception as err:
        _LOGGER.error("Error updating entities for entry %s: %s", entry_id, err) 