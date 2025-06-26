"""SMS sending service for SmartSMS integration."""
from __future__ import annotations

import logging
import asyncio
import aiohttp
import base64
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_API_USERNAME,
    CONF_API_PASSWORD,
    CONF_DEFAULT_SENDER,
    DOMAIN,
    MM_API_BASE_URL,
    MM_SEND_ENDPOINT,
    SERVICE_SEND_SMS,
)

_LOGGER = logging.getLogger(__name__)

# Service schemas
SEND_SMS_SCHEMA = vol.Schema({
    vol.Required("to"): cv.string,
    vol.Required("message"): cv.string,
    vol.Optional("sender"): cv.string,
    vol.Optional("custom_ref"): cv.string,
})


async def async_register_services(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Register SMS sending services."""
    
    async def async_send_sms(call: ServiceCall) -> None:
        """Send SMS via Mobile Message API."""
        try:
            to_number = call.data["to"]
            message = call.data["message"]
            sender_from_call = call.data.get("sender")
            # Check both entry.data and entry.options for default sender
            sender_from_config = entry.data.get(CONF_DEFAULT_SENDER, "") or entry.options.get(CONF_DEFAULT_SENDER, "")
            sender = sender_from_call or sender_from_config
            custom_ref = call.data.get("custom_ref", "")
            
            # Debug logging
            _LOGGER.debug("Service call data: %s", call.data)
            _LOGGER.debug("Entry data keys: %s", list(entry.data.keys()))
            _LOGGER.debug("Entry options keys: %s", list(entry.options.keys()) if entry.options else "No options")
            _LOGGER.debug("Sender from call: %r", sender_from_call)
            _LOGGER.debug("Sender from config data: %r", entry.data.get(CONF_DEFAULT_SENDER, ""))
            _LOGGER.debug("Sender from config options: %r", entry.options.get(CONF_DEFAULT_SENDER, "") if entry.options else "")
            _LOGGER.debug("Final sender: %r", sender)
            
            if not sender:
                _LOGGER.error("No sender ID provided and no default sender configured. Call data: %s, Config keys: %s", call.data, list(entry.data.keys()))
                return
            
            # Validate phone number format
            if not _is_valid_phone_number(to_number):
                _LOGGER.error("Invalid phone number format: %s", to_number)
                return
            
            # Validate message length (Mobile Message allows up to 765 characters)
            if len(message) > 765:
                _LOGGER.error("Message too long (%d chars). Maximum is 765 characters", len(message))
                return
            
            # Send SMS via Mobile Message API
            result = await _send_sms_api(
                hass,
                entry.data[CONF_API_USERNAME],
                entry.data[CONF_API_PASSWORD],
                to_number,
                message,
                sender,
                custom_ref
            )
            
            if result:
                _LOGGER.info("SMS sent successfully to %s", to_number)
            else:
                _LOGGER.error("Failed to send SMS to %s", to_number)
                
        except Exception as err:
            _LOGGER.exception("Error sending SMS: %s", err)
    
    # Register the service
    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_SMS,
        async_send_sms,
        schema=SEND_SMS_SCHEMA,
    )
    
    _LOGGER.info("Registered SmartSMS sending service")


async def async_unregister_services(hass: HomeAssistant) -> None:
    """Unregister SMS services."""
    hass.services.async_remove(DOMAIN, SERVICE_SEND_SMS)
    _LOGGER.info("Unregistered SmartSMS sending service")


async def _send_sms_api(
    hass: HomeAssistant,
    api_username: str,
    api_password: str,
    to_number: str,
    message: str,
    sender: str,
    custom_ref: str = "",
) -> bool:
    """Send SMS via Mobile Message API."""
    try:
        # Prepare API request
        url = f"{MM_API_BASE_URL}{MM_SEND_ENDPOINT}"
        
        # Create basic auth header
        credentials = f"{api_username}:{api_password}"
        encoded_credentials = base64.b64encode(credentials.encode()).decode()
        
        headers = {
            "Authorization": f"Basic {encoded_credentials}",
            "Content-Type": "application/json",
        }
        
        # Prepare payload
        payload = {
            "messages": [
                {
                    "to": to_number,
                    "message": message,
                    "sender": sender,
                }
            ]
        }
        
        # Add custom reference if provided
        if custom_ref:
            payload["messages"][0]["custom_ref"] = custom_ref
        
        _LOGGER.debug("Sending SMS API request to %s", url)
        _LOGGER.debug("Payload: %s", payload)
        
        # Make API request
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload, headers=headers) as response:
                response_text = await response.text()
                
                _LOGGER.debug("SMS API response status: %d", response.status)
                _LOGGER.debug("SMS API response: %s", response_text)
                
                if response.status == 200:
                    try:
                        response_data = await response.json()
                        if response_data.get("status") == "complete":
                            # Check individual message results
                            results = response_data.get("results", [])
                            if results and results[0].get("status") == "success":
                                message_id = results[0].get("message_id", "")
                                cost = results[0].get("cost", 0)
                                _LOGGER.info(
                                    "SMS sent successfully - ID: %s, Cost: %s credits",
                                    message_id,
                                    cost
                                )
                                return True
                            else:
                                error = results[0].get("status", "Unknown error") if results else "No results"
                                _LOGGER.error("SMS API returned error: %s", error)
                                return False
                        else:
                            _LOGGER.error("SMS API status not complete: %s", response_data.get("status"))
                            return False
                    except Exception as e:
                        _LOGGER.error("Failed to parse SMS API response as JSON: %s", e)
                        return False
                else:
                    _LOGGER.error("SMS API returned status %d: %s", response.status, response_text)
                    return False
                    
    except asyncio.TimeoutError:
        _LOGGER.error("SMS API request timed out")
        return False
    except aiohttp.ClientError as e:
        _LOGGER.error("SMS API request failed: %s", e)
        return False
    except Exception as e:
        _LOGGER.exception("Unexpected error sending SMS: %s", e)
        return False


def _is_valid_phone_number(phone: str) -> bool:
    """Validate phone number format for Mobile Message API."""
    if not phone:
        return False
    
    # Remove any spaces, dashes, or parentheses
    clean_phone = "".join(c for c in phone if c.isdigit() or c == "+")
    
    # Check for international format (+country code + number)
    if clean_phone.startswith('+'):
        # International format: minimum 8 digits, maximum 15 digits after +
        return len(clean_phone) >= 9 and len(clean_phone) <= 16 and clean_phone[1:].isdigit()
    
    # Check for Australian local format (0xxxxxxxxx)
    if clean_phone.startswith('0'):
        # Australian local format: 10 digits starting with 0
        return len(clean_phone) == 10 and clean_phone.isdigit()
    
    # Check for basic numeric format (for flexibility)
    return len(clean_phone) >= 8 and len(clean_phone) <= 15 and clean_phone.isdigit() 