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
    CONF_API_PASSWORD,
    CONF_API_USERNAME,
    CONF_DEFAULT_SENDER,
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
            # Validate the Mobile Message credentials
            try:
                await self._validate_credentials(
                    user_input[CONF_API_USERNAME], 
                    user_input[CONF_API_PASSWORD]
                )
                
                # Store basic config
                self.data.update(user_input)
                
                # Generate webhook ID and secret
                self.data[CONF_WEBHOOK_ID] = self._generate_webhook_id()
                self.data[CONF_WEBHOOK_SECRET] = self._generate_webhook_secret()
                
                # Create the config entry directly since sender ID is now required upfront
                return self.async_create_entry(
                    title=self.data[CONF_NAME],
                    data=self.data,
                )
                
            except InvalidCredentials:
                errors["base"] = "invalid_auth"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_NAME, default="SmartSMS"): str,
                vol.Required(CONF_API_USERNAME): str,
                vol.Required(CONF_API_PASSWORD): str,
                vol.Required(CONF_DEFAULT_SENDER): str,
            }),
            errors=errors,
        )

    async def async_step_filters(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure message filters."""
        if user_input is not None:
            # Add default sender to config
            if user_input.get(CONF_DEFAULT_SENDER):
                self.data[CONF_DEFAULT_SENDER] = user_input[CONF_DEFAULT_SENDER].strip()
            
            # Create the config entry
            return self.async_create_entry(
                title=self.data[CONF_NAME],
                data=self.data,
            )

        return self.async_show_form(
            step_id="filters",
            data_schema=vol.Schema({
                vol.Optional(CONF_DEFAULT_SENDER): str,
            }),
            description_placeholders={
                "webhook_url": self._get_webhook_url(),
            },
        )

    async def _validate_credentials(self, username: str, password: str) -> None:
        """Validate Mobile Message credentials."""
        # Basic validation - ensure credentials are provided
        if not username or not username.strip():
            raise InvalidCredentials("API Username is required")
        if not password or not password.strip():
            raise InvalidCredentials("API Password is required")
        
        # For now, skip API validation since Mobile Message doesn't have a simple test endpoint
        # The credentials will be tested when the first webhook is received
        _LOGGER.info("Mobile Message credentials accepted (will be validated on first webhook)")
        
        # TODO: Future improvement - test with a simple API call when we find the right endpoint

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

        # Get current default sender (check both data and options for backward compatibility)
        current_default_sender = self._config_entry.data.get(CONF_DEFAULT_SENDER, "") or self._config_entry.options.get(CONF_DEFAULT_SENDER, "")

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional(CONF_DEFAULT_SENDER, default=current_default_sender): str,
            }),
            description_placeholders={
                "webhook_url": webhook_url,
            },
        ) 