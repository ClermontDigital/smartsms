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
            twiml_error = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'
            return web.Response(status=413, text=twiml_error, content_type="application/xml")
        
        # Find config entry
        entry_id = _WEBHOOK_TO_ENTRY.get(webhook_id)
        if not entry_id:
            _LOGGER.error("No config entry found for webhook ID: %s", webhook_id)
            twiml_error = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'
            return web.Response(status=404, text=twiml_error, content_type="application/xml")
        
        # Get config entry
        config_entry = None
        for entry in hass.config_entries.async_entries(DOMAIN):
            if entry.entry_id == entry_id:
                config_entry = entry
                break
        
        if not config_entry:
            _LOGGER.error("Config entry %s not found", entry_id)
            twiml_error = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'
            return web.Response(status=404, text=twiml_error, content_type="application/xml")
        
        # Parse request data
        data = await _parse_request_data(request)
        if not data:
            _LOGGER.error("Failed to parse webhook request data")
            twiml_error = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'
            return web.Response(status=400, text=twiml_error, content_type="application/xml")
        
        # Validate Twilio signature if enabled
        auth_token = config_entry.data.get(CONF_AUTH_TOKEN)
        if auth_token and not await _validate_twilio_signature(request, data, auth_token):
            _LOGGER.warning("Invalid Twilio signature for webhook %s", webhook_id)
            twiml_error = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'
            return web.Response(status=403, text=twiml_error, content_type="application/xml")
        
        # Extract message data
        message_data = _extract_message_data(data)
        if not message_data:
            _LOGGER.error("Failed to extract valid message data")
            twiml_error = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'
            return web.Response(status=400, text=twiml_error, content_type="application/xml")
        
        # Apply filters
        if not _should_process_message(config_entry.data, message_data):
            _LOGGER.debug("Message filtered out from %s", message_data[ATTR_SENDER])
            twiml = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'
            return web.Response(status=200, text=twiml, content_type="application/xml")
        
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
        
        # Return TwiML response that Twilio expects
        twiml = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'
        return web.Response(status=200, text=twiml, content_type="application/xml")
        
    except Exception as err:
        _LOGGER.exception("Error processing webhook %s: %s", webhook_id, err)
        twiml_error = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'
        return web.Response(status=500, text=twiml_error, content_type="application/xml")


async def _parse_request_data(request: web.Request) -> dict[str, Any] | None:
    """Parse request data from various formats."""
    try:
        # Read body only once
        body = await request.read()
        
        # Try different encodings if UTF-8 fails
        try:
            body_str = body.decode('utf-8')
        except UnicodeDecodeError:
            try:
                body_str = body.decode('latin-1')
                _LOGGER.warning("Using latin-1 encoding for webhook data")
            except UnicodeDecodeError:
                body_str = body.decode('utf-8', errors='replace')
                _LOGGER.warning("Using UTF-8 with error replacement for webhook data")
        
        # Try form data first (most common for Twilio)
        if request.content_type == 'application/x-www-form-urlencoded':
            # parse_qs automatically handles URL decoding
            return dict(parse_qs(body_str, keep_blank_values=True))
        
        # Try JSON
        if 'json' in request.content_type:
            import json
            return json.loads(body_str)
        
        # Manual parse for form data (fallback)
        return dict(parse_qs(body_str, keep_blank_values=True))
        
    except Exception as err:
        _LOGGER.error("Error parsing request data: %s", err)
        return None


async def _validate_twilio_signature(
    request: web.Request, data: dict[str, Any], auth_token: str
) -> bool:
    """Validate Twilio webhook signature."""
    try:
        signature = request.headers.get("X-Twilio-Signature")
        if not signature:
            return False
        
        # Get URL and sorted data for signature
        url = str(request.url)
        sorted_data = sorted(data.items())
        body = "&".join([f"{k}={v[0] if isinstance(v, list) else v}" for k, v in sorted_data])
        
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


def _extract_message_data(data: dict[str, Any]) -> dict[str, Any] | None:
    """Extract SMS message data from webhook payload."""
    try:
        # Handle list values from form parsing
        def get_value(key: str) -> str:
            value = data.get(key, "")
            if isinstance(value, list):
                return value[0] if value else ""
            return str(value)
        
        # Extract Twilio fields
        body = get_value(TWILIO_BODY)
        sender = get_value(TWILIO_FROM)
        to_number = get_value(TWILIO_TO)
        
        # Debug log the raw extracted values
        _LOGGER.debug("RAW EXTRACTED - Body: %r, From: %r, To: %r", body, sender, to_number)
        
        if not body or not sender:
            _LOGGER.error("Missing required fields: Body=%s, From=%s", body, sender)
            return None
        
        # Parse timestamp
        timestamp_str = get_value(TWILIO_TIMESTAMP)
        if timestamp_str:
            try:
                # Try parsing Twilio timestamp format
                timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt_util.UTC)
            except ValueError:
                timestamp = dt_util.utcnow()
        else:
            timestamp = dt_util.utcnow()
        
        # Validate phone numbers
        if not _is_valid_phone(sender) or not _is_valid_phone(to_number):
            _LOGGER.warning("Invalid phone number format: From=%s, To=%s", sender, to_number)
        
        # Clean up the message body to remove CR/LF and other problematic characters
        clean_body = _clean_message_body(body)
        
        return {
            ATTR_BODY: clean_body[:1000],  # Limit message length
            ATTR_SENDER: sender,
            ATTR_TO_NUMBER: to_number,
            ATTR_MESSAGE_SID: get_value(TWILIO_MESSAGE_SID),
            ATTR_TIMESTAMP: timestamp.isoformat(),
            ATTR_PROVIDER: "twilio",
        }
        
    except Exception as err:
        _LOGGER.error("Error extracting message data: %s", err)
        return None


def _is_valid_phone(phone: str) -> bool:
    """Validate phone number format."""
    if not phone:
        return False
    # Basic phone validation - starts with + and contains only digits
    return bool(re.match(r'^\+[1-9]\d{1,14}$', phone))


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