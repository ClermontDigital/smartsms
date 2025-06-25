"""Config flow for SmartSMS integration."""
from __future__ import annotations

import logging
import secrets
import string
from typing import Any

import voluptuous as vol
from homeassistant import config_entries  # type: ignore
from homeassistant.const import CONF_NAME  # type: ignore
from homeassistant.core import HomeAssistant, callback  # type: ignore
from homeassistant.data_entry_flow import FlowResult  # type: ignore

from .const import (
    CONF_ACCOUNT_SID,
    CONF_AUTH_TOKEN,
    CONF_KEYWORDS,
    CONF_SENDER_BLACKLIST,
    CONF_SENDER_WHITELIST,
    CONF_WEBHOOK_ID,
    CONF_WEBHOOK_SECRET,
    DEFAULT_WEBHOOK_SECRET_LENGTH,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class InvalidCredentials(Exception):
    """Exception to indicate invalid credentials."""


class SmartSMSConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for SmartSMS."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self.data: dict[str, Any] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> SmartSMSOptionsFlow:
        """Create the options flow."""
        return SmartSMSOptionsFlow(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Validate the Twilio credentials
            try:
                await self._validate_credentials(
                    user_input[CONF_ACCOUNT_SID], 
                    user_input[CONF_AUTH_TOKEN]
                )
                
                # Store basic config
                self.data.update(user_input)
                
                # Generate webhook ID and secret
                self.data[CONF_WEBHOOK_ID] = self._generate_webhook_id()
                self.data[CONF_WEBHOOK_SECRET] = self._generate_webhook_secret()
                
                return await self.async_step_filters()
                
            except InvalidCredentials:
                errors["base"] = "invalid_auth"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_NAME, default="SmartSMS"): str,
                vol.Required(CONF_ACCOUNT_SID): str,
                vol.Required(CONF_AUTH_TOKEN): str,
            }),
            errors=errors,
        )

    async def async_step_filters(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure message filters."""
        if user_input is not None:
            # Process filter lists
            sender_whitelist = []
            if user_input.get(CONF_SENDER_WHITELIST):
                sender_whitelist = [
                    phone.strip() 
                    for phone in user_input[CONF_SENDER_WHITELIST].split(",")
                    if phone.strip()
                ]
            
            sender_blacklist = []
            if user_input.get(CONF_SENDER_BLACKLIST):
                sender_blacklist = [
                    phone.strip() 
                    for phone in user_input[CONF_SENDER_BLACKLIST].split(",")
                    if phone.strip()
                ]
            
            keywords = []
            if user_input.get(CONF_KEYWORDS):
                keywords = [
                    keyword.strip() 
                    for keyword in user_input[CONF_KEYWORDS].split(",")
                    if keyword.strip()
                ]
            
            # Add filters to config
            if sender_whitelist:
                self.data[CONF_SENDER_WHITELIST] = sender_whitelist
            if sender_blacklist:
                self.data[CONF_SENDER_BLACKLIST] = sender_blacklist
            if keywords:
                self.data[CONF_KEYWORDS] = keywords
            
            # Create the config entry
            return self.async_create_entry(
                title=self.data[CONF_NAME],
                data=self.data,
            )

        return self.async_show_form(
            step_id="filters",
            data_schema=vol.Schema({
                vol.Optional(CONF_SENDER_WHITELIST): str,
                vol.Optional(CONF_SENDER_BLACKLIST): str,
                vol.Optional(CONF_KEYWORDS): str,
            }),
            description_placeholders={
                "webhook_url": self._get_webhook_url(),
            },
        )

    async def _validate_credentials(self, account_sid: str, auth_token: str) -> None:
        """Validate Twilio credentials."""
        try:
            from twilio.rest import Client
            
            client = Client(account_sid, auth_token)
            
            # Try to fetch account info to validate credentials
            await self.hass.async_add_executor_job(
                lambda: client.api.accounts(account_sid).fetch()
            )
            
        except Exception as err:
            _LOGGER.error("Failed to validate Twilio credentials: %s", err)
            raise InvalidCredentials from err

    def _generate_webhook_id(self) -> str:
        """Generate a unique webhook ID."""
        return secrets.token_urlsafe(16)

    def _generate_webhook_secret(self) -> str:
        """Generate a webhook secret."""
        alphabet = string.ascii_letters + string.digits
        return "".join(secrets.choice(alphabet) for _ in range(DEFAULT_WEBHOOK_SECRET_LENGTH))

    def _get_webhook_url(self) -> str:
        """Get the webhook URL for display."""
        base_url = self.hass.config.external_url or "http://your-home-assistant.local:8123"
        webhook_id = self.data.get(CONF_WEBHOOK_ID, "YOUR_WEBHOOK_ID")
        return f"{base_url}/api/webhook/{webhook_id}"


class SmartSMSOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for SmartSMS."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        # Get current webhook URL
        webhook_id = self._config_entry.data.get(CONF_WEBHOOK_ID)
        base_url = self.hass.config.external_url or "http://your-home-assistant.local:8123"
        webhook_url = f"{base_url}/api/webhook/{webhook_id}"

        # Get current filters
        current_whitelist = ", ".join(self._config_entry.data.get(CONF_SENDER_WHITELIST, []))
        current_blacklist = ", ".join(self._config_entry.data.get(CONF_SENDER_BLACKLIST, []))
        current_keywords = ", ".join(self._config_entry.data.get(CONF_KEYWORDS, []))

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional(CONF_SENDER_WHITELIST, default=current_whitelist): str,
                vol.Optional(CONF_SENDER_BLACKLIST, default=current_blacklist): str,
                vol.Optional(CONF_KEYWORDS, default=current_keywords): str,
            }),
            description_placeholders={
                "webhook_url": webhook_url,
            },
        ) 