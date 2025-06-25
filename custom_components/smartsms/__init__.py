"""The SmartSMS integration."""
from __future__ import annotations

import logging
from typing import Any
import asyncio
from datetime import datetime, timezone, timedelta
from twilio.rest import Client


def _sanitize_message_text(text: str) -> str:
    """Clean SMS message body by keeping ONLY printable ASCII characters."""
    if not text:
        return text
    
    import re
    import html
    
    _LOGGER.debug("POLLING ORIGINAL SMS BODY: %r (len=%d)", text, len(text))
    
    # Step 1: Handle URL decoding if needed (defensive)
    try:
        from urllib.parse import unquote_plus
        if '%' in text and re.search(r'%[0-9A-Fa-f]{2}', text):
            text = unquote_plus(text)
            _LOGGER.debug("POLLING URL decoded: %r", text)
    except Exception:
        pass
    
    # Step 2: HTML entity decoding
    try:
        text = html.unescape(text)
        _LOGGER.debug("POLLING HTML unescaped: %r", text)
    except Exception:
        pass
    
    # Step 3: AGGRESSIVE ASCII-ONLY FILTERING + MARKDOWN REMOVAL
    # Keep only printable ASCII characters (32-126) but exclude markdown chars
    # This removes ALL Unicode, control chars, invisible characters AND markdown
    ascii_chars = []
    for char in text:
        char_code = ord(char)
        if 32 <= char_code <= 126:  # Printable ASCII range
            # But specifically remove asterisks and other markdown characters
            if char not in ['*', '_', '`', '#', '[', ']', '!', '|', '\\', '^', '>', '<', '~']:
                ascii_chars.append(char)
            else:
                _LOGGER.debug("POLLING REMOVED markdown char: %r (code=%d)", char, char_code)
        elif char_code == 9:  # Tab -> space
            ascii_chars.append(' ')
        elif char_code in (10, 13):  # LF, CR -> space
            ascii_chars.append(' ')
        else:
            # Log what we're removing for debugging
            _LOGGER.debug("POLLING REMOVED non-ASCII char: %r (code=%d)", char, char_code)
    
    clean_body = ''.join(ascii_chars)
    _LOGGER.debug("POLLING ASCII-only result: %r", clean_body)
    
    # Step 4: Normalize whitespace
    clean_body = re.sub(r'\s+', ' ', clean_body)
    clean_body = clean_body.strip()
    
    _LOGGER.debug("POLLING FINAL CLEANED: %r (len=%d)", clean_body, len(clean_body))
    
    return clean_body

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN
from .data_store import SmartSMSDataStore
from .webhook import async_register_webhook, async_unregister_webhook

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR]

# Debug: Log when module is imported
_LOGGER.warning("SMARTSMS MODULE IMPORTED - __init__.py loaded")


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up SmartSMS from a config entry."""
    _LOGGER.warning("SMARTSMS SETUP STARTING: %s", entry.title)
    _LOGGER.warning("SMARTSMS CONFIG DATA: %s", entry.data)
    
    try:
        # Initialize domain data structure
        hass.data.setdefault(DOMAIN, {})
        
        # Initialize data store
        data_store = SmartSMSDataStore(hass, entry.entry_id)
        
        # Set up entry data structure
        hass.data[DOMAIN][entry.entry_id] = {
            "config": entry.data,
            "data_store": data_store,
        }
        
        # Register webhook
        await async_register_webhook(hass, entry)
        
        # Setup platforms
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        
        # Register device
        device_registry = dr.async_get(hass)
        device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, entry.entry_id)},
            manufacturer="SmartSMS",
            name="SMS Gateway",
            model="SmartSMS",
            configuration_url="https://console.twilio.com/",
        )
        
        # --- POLLING TASK ---
        async def poll_twilio_messages():
            """Poll Twilio for new inbound messages every 60 seconds."""
            _LOGGER.warning("SMARTSMS POLLING TASK STARTED")
            account_sid = entry.data.get("account_sid")
            auth_token = entry.data.get("auth_token")
            
            if not account_sid or not auth_token:
                _LOGGER.error("SMARTSMS POLLING: Missing Twilio credentials")
                return
                
            try:
                client = Client(account_sid, auth_token)
                _LOGGER.info("SMARTSMS POLLING: Twilio client initialized")
            except Exception as err:
                _LOGGER.error("SMARTSMS POLLING: Failed to create Twilio client: %s", err)
                return
            
            # Use a set to track processed message SIDs instead of just last_seen_sid
            processed_sids = set()
            
            while True:
                try:
                    _LOGGER.debug("SMARTSMS POLLING: Fetching messages from Twilio...")
                    
                    # Fetch all inbound messages from the last 24 hours
                    messages = await hass.async_add_executor_job(
                        lambda: client.messages.list(
                            date_sent_after=(datetime.now(timezone.utc) - timedelta(hours=24)),
                            limit=50
                        )
                    )
                    
                    _LOGGER.debug("SMARTSMS POLLING: Found %d total messages", len(messages))
                    
                    # Filter for inbound messages only
                    inbound_messages = [msg for msg in messages if msg.direction == "inbound"]
                    _LOGGER.debug("SMARTSMS POLLING: Found %d inbound messages", len(inbound_messages))
                    
                    if not inbound_messages:
                        _LOGGER.debug("SMARTSMS POLLING: No inbound messages found")
                        await asyncio.sleep(60)
                        continue
                    
                    # Find new messages (not in processed_sids set)
                    new_messages = []
                    for msg in inbound_messages:
                        if msg.sid not in processed_sids:
                            new_messages.append(msg)
                    
                    _LOGGER.debug("SMARTSMS POLLING: Found %d new messages", len(new_messages))
                    
                    if new_messages:
                        # Process messages in chronological order (oldest first)
                        new_messages.sort(key=lambda x: x.date_sent or datetime.min.replace(tzinfo=timezone.utc))
                        
                        for msg in new_messages:
                            _LOGGER.info("SMARTSMS POLLING: Processing message SID %s from %s", msg.sid, msg.from_)
                            
                            # DEBUG: Inspect the raw Twilio message object
                            _LOGGER.error("TWILIO MSG OBJECT DEBUG:")
                            _LOGGER.error("  msg.body type: %s", type(msg.body))
                            _LOGGER.error("  msg.body raw: %r", msg.body)
                            _LOGGER.error("  msg.body length: %d", len(msg.body) if msg.body else 0)
                            
                            # Show each character with its ASCII code
                            if msg.body:
                                char_debug = []
                                for i, char in enumerate(msg.body):
                                    char_debug.append(f"[{i}]='{char}'({ord(char)})")
                                _LOGGER.error("  Character breakdown: %s", ' '.join(char_debug[:50]))  # First 50 chars
                            
                            # Sanitize message body to prevent markdown formatting issues
                            raw_body = msg.body[:1000] if msg.body else ""
                            _LOGGER.warning("SMARTSMS RAW MESSAGE: '%s' (len=%d, repr=%r)", raw_body, len(raw_body), raw_body)
                            sanitized_body = _sanitize_message_text(raw_body) if raw_body else ""
                            _LOGGER.warning("SMARTSMS SANITIZED: '%s' (len=%d, repr=%r)", sanitized_body, len(sanitized_body), sanitized_body)
                            
                            # Build message_data dict as in webhook
                            message_data = {
                                "body": sanitized_body,
                                "raw_body": raw_body,  # Keep original for automations that need it
                                "sender": msg.from_,
                                "to_number": msg.to,
                                "message_sid": msg.sid,
                                "timestamp": msg.date_sent.isoformat() if msg.date_sent else datetime.now(timezone.utc).isoformat(),
                                "provider": "twilio",
                            }
                            
                            # Apply filters (reuse functions from webhook.py)
                            from .webhook import _should_process_message, _check_keywords, _update_entities
                            config = entry.data
                            
                            if not _should_process_message(config, message_data):
                                _LOGGER.debug("SMARTSMS POLLING: Message filtered out from %s", message_data["sender"])
                                # Still mark as processed even if filtered
                                processed_sids.add(msg.sid)
                                continue
                            
                            matched_keywords = _check_keywords(config.get("keywords", []), message_data["body"])
                            if matched_keywords:
                                message_data["matched_keywords"] = matched_keywords
                            
                            # Fire events
                            hass.bus.async_fire("smartsms_message_received", message_data)
                            if matched_keywords:
                                hass.bus.async_fire("smartsms_keyword_matched", message_data)
                            
                            # Update entities
                            await _update_entities(hass, entry.entry_id, message_data)
                            
                            _LOGGER.info("SMARTSMS POLLING: Processed SMS from %s: %s", 
                                        message_data["sender"], 
                                        message_data["body"][:50] + "..." if len(message_data["body"]) > 50 else message_data["body"])
                            
                            # Mark message as processed
                            processed_sids.add(msg.sid)
                        
                        _LOGGER.info("SMARTSMS POLLING: Processed %d new messages", len(new_messages))
                    
                    # Clean up old SIDs (keep only last 1000 to prevent memory growth)
                    if len(processed_sids) > 1000:
                        # Convert to list, sort by age (would need message timestamps), keep newest 500
                        # For simplicity, just clear half when we hit the limit
                        processed_sids_list = list(processed_sids)
                        processed_sids.clear()
                        processed_sids.update(processed_sids_list[-500:])
                        _LOGGER.debug("SMARTSMS POLLING: Cleaned up processed SIDs, keeping %d", len(processed_sids))
                    
                    await asyncio.sleep(60)  # Poll every 60 seconds
                    
                except Exception as err:
                    _LOGGER.error("SMARTSMS POLLING: Error in polling loop: %s", err)
                    _LOGGER.exception("SMARTSMS POLLING: Full error trace:")
                    await asyncio.sleep(60)  # Wait before retrying
        
        # Start polling task
        poll_task = hass.async_create_task(poll_twilio_messages())
        hass.data[DOMAIN][entry.entry_id]["poll_task"] = poll_task
        
        _LOGGER.warning("SMARTSMS SETUP COMPLETE: %s", entry.title)
        return True
        
    except Exception as err:
        _LOGGER.error("SMARTSMS SETUP FAILED: %s", err)
        _LOGGER.exception("SMARTSMS FULL ERROR TRACE:")
        # Clean up on failure
        if entry.entry_id in hass.data.get(DOMAIN, {}):
            hass.data[DOMAIN].pop(entry.entry_id)
        raise ConfigEntryNotReady(f"Failed to set up SmartSMS: {err}") from err


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.info("Unloading SmartSMS integration: %s", entry.title)
    
    try:
        # Cancel polling task first
        entry_data = hass.data[DOMAIN].get(entry.entry_id, {})
        poll_task = entry_data.get("poll_task")
        if poll_task and not poll_task.done():
            _LOGGER.info("Cancelling SmartSMS polling task")
            poll_task.cancel()
            try:
                await poll_task
            except asyncio.CancelledError:
                pass
        
        # Unregister webhook
        await async_unregister_webhook(hass, entry)
        
        # Unload platforms
        unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
        
        if unload_ok:
            # Clean up data store
            data_store = entry_data.get("data_store")
            if data_store:
                await data_store.cleanup()
            
            # Remove entry data
            hass.data[DOMAIN].pop(entry.entry_id, None)
            if not hass.data[DOMAIN]:
                hass.data.pop(DOMAIN, None)
                
        _LOGGER.info("SmartSMS integration unloaded: %s", entry.title)
        return unload_ok
        
    except Exception as err:
        _LOGGER.error("Failed to unload SmartSMS integration: %s", err)
        return False 