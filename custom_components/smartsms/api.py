"""WebSocket API for the messages card.

Admins only. Message history and contact names are personal, and anything kept in an
entity's state or attributes can be read by every Home Assistant user, so they are
only handed out here. Sending goes through the smartsms.send_sms action, which logs
what it sends.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.util import dt as dt_util

from .const import CONTACT_NAME_MAX_LENGTH, DOMAIN, SIGNAL_HISTORY_UPDATED
from .data_store import SmartSMSDataStore
from .webhook import normalise_number


def _stores(hass: HomeAssistant) -> list[SmartSMSDataStore]:
    return [
        entry.runtime_data
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED
    ]


def _when(message: dict[str, Any]) -> datetime:
    when = dt_util.parse_datetime(message.get("timestamp") or "") or dt_util.utc_from_timestamp(0)
    return when if when.tzinfo else when.replace(tzinfo=dt_util.UTC)


@callback
def _snapshot(hass: HomeAssistant) -> dict[str, Any]:
    """Every loaded entry's messages, oldest first, and the contact names."""
    stores = _stores(hass)
    messages = [message for store in stores for message in store.history]
    if len(stores) > 1:  # each store is already in order
        messages.sort(key=_when)
    contacts: dict[str, str] = {}
    for store in stores:
        contacts.update(store.contacts)
    return {"messages": messages, "contacts": contacts, "can_send": bool(stores)}


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/history"})
@callback
def ws_history(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Messages in and out, oldest first, and contact names."""
    connection.send_result(msg["id"], _snapshot(hass))


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/subscribe"})
@callback
def ws_subscribe(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """The same as smartsms/history, then again whenever it changes."""

    @callback
    def _forward() -> None:
        connection.send_message(websocket_api.event_message(msg["id"], _snapshot(hass)))

    connection.subscriptions[msg["id"]] = async_dispatcher_connect(
        hass, SIGNAL_HISTORY_UPDATED, _forward
    )
    connection.send_result(msg["id"])
    _forward()


@websocket_api.require_admin
@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/contact_set",
    vol.Required("number"): str,
    vol.Optional("name", default=""): str,
})
@callback
def ws_contact_set(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Name a number, or forget its name (empty name)."""
    stores = _stores(hass)
    thread = normalise_number(msg["number"])
    if not stores:
        connection.send_error(msg["id"], "not_loaded", "SmartSMS is not set up")
        return
    if not thread:
        connection.send_error(msg["id"], "invalid_format", "No number given")
        return
    name = " ".join(msg["name"].split())[:CONTACT_NAME_MAX_LENGTH]
    stores[0].async_set_contact(thread, name)
    for other in stores[1:]:  # one name per number
        other.async_set_contact(thread, "")
    connection.send_result(msg["id"], {"thread": thread, "name": name})


@callback
def async_register_api(hass: HomeAssistant) -> None:
    """Register the commands (once per HA run, from async_setup)."""
    for command in (ws_history, ws_subscribe, ws_contact_set):
        websocket_api.async_register_command(hass, command)
