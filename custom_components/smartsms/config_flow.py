"""Config flow for the SmartSMS integration."""
from __future__ import annotations

import secrets
from typing import Any

import voluptuous as vol
from homeassistant.components import webhook
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.network import NoURLAvailableError, get_url
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig

from .const import (
    CONF_API_PASSWORD,
    CONF_API_USERNAME,
    CONF_DEFAULT_SENDER,
    CONF_KEYWORDS,
    CONF_SENDER_BLACKLIST,
    CONF_SENDER_WHITELIST,
    CONF_WEBHOOK_ID,
    DOMAIN,
)

LIST_SELECTOR = TextSelector(TextSelectorConfig(multiple=True))


async def async_webhook_url(hass: HomeAssistant, webhook_id: str) -> str:
    """The public URL to paste into Mobile Message.

    With Home Assistant Cloud that's a cloudhook (created if needed, and reused if
    one already exists); otherwise the external URL. Never the LAN address.
    """
    if "cloud" in hass.config.components:
        from homeassistant.components import cloud  # only when Cloud is set up

        if cloud.async_active_subscription(hass):
            return await cloud.async_get_or_create_cloudhook(hass, webhook_id)
    try:
        base = get_url(hass, allow_internal=False, allow_cloud=False)
    except NoURLAvailableError:
        return "(no public URL - set up Home Assistant Cloud or an external URL first)"
    return f"{base}{webhook.async_generate_path(webhook_id)}"


class SmartSMSConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for SmartSMS."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._data: dict[str, Any] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> SmartSMSOptionsFlow:
        """Create the options flow."""
        return SmartSMSOptionsFlow(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the Mobile Message credentials and sender ID."""
        errors: dict[str, str] = {}

        if user_input is not None:
            user_input = {k: v.strip() if isinstance(v, str) else v for k, v in user_input.items()}
            if not user_input[CONF_API_USERNAME] or not user_input[CONF_API_PASSWORD]:
                errors["base"] = "invalid_auth"
            elif not user_input[CONF_DEFAULT_SENDER]:
                errors[CONF_DEFAULT_SENDER] = "sender_required"
            else:
                await self.async_set_unique_id(user_input[CONF_API_USERNAME].lower())
                self._abort_if_unique_id_configured()
                self._data = {**user_input, CONF_WEBHOOK_ID: secrets.token_urlsafe(16)}
                return await self.async_step_webhook()

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

    async def async_step_webhook(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the webhook URL to copy into Mobile Message, then create the entry."""
        if user_input is not None:
            return self.async_create_entry(title=self._data[CONF_NAME], data=self._data)

        return self.async_show_form(
            step_id="webhook",
            description_placeholders={
                "webhook_url": await async_webhook_url(self.hass, self._data[CONF_WEBHOOK_ID]),
            },
        )


class SmartSMSOptionsFlow(OptionsFlow):
    """Sender ID and inbound message filters."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize the options flow."""
        self._entry = config_entry

    def _current(self, key: str, default: Any) -> Any:
        # `or`: a 0.9.x options flow could have saved an empty sender
        return self._entry.options.get(key) or self._entry.data.get(key, default)

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}
        if user_input is not None:
            sender = (user_input.get(CONF_DEFAULT_SENDER) or "").strip()
            if not sender:
                errors[CONF_DEFAULT_SENDER] = "sender_required"
            else:
                return self.async_create_entry(
                    data={
                        CONF_DEFAULT_SENDER: sender,
                        **{
                            key: [v.strip() for v in user_input.get(key, []) if v.strip()]
                            for key in (CONF_SENDER_WHITELIST, CONF_SENDER_BLACKLIST, CONF_KEYWORDS)
                        },
                    }
                )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(
                    CONF_DEFAULT_SENDER, default=self._current(CONF_DEFAULT_SENDER, "")
                ): str,
                vol.Optional(
                    CONF_SENDER_WHITELIST, default=self._current(CONF_SENDER_WHITELIST, [])
                ): LIST_SELECTOR,
                vol.Optional(
                    CONF_SENDER_BLACKLIST, default=self._current(CONF_SENDER_BLACKLIST, [])
                ): LIST_SELECTOR,
                vol.Optional(
                    CONF_KEYWORDS, default=self._current(CONF_KEYWORDS, [])
                ): LIST_SELECTOR,
            }),
            errors=errors,
            description_placeholders={
                "webhook_url": await async_webhook_url(self.hass, self._entry.data[CONF_WEBHOOK_ID]),
            },
        )
