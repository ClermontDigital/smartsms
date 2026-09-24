"""Persistent storage for received messages."""
from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store

from .const import DOMAIN, SIGNAL_MESSAGE_STORED, STORAGE_SAVE_DELAY, STORAGE_VERSION


class SmartSMSDataStore:
    """The latest received message and the running count, kept across restarts."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Initialize the data store."""
        self.hass = hass
        self.entry_id = entry_id
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}"
        )
        self.latest_message: dict[str, Any] = {}
        self.message_count: int = 0

    async def async_load(self) -> None:
        """Load the saved state, if there is any."""
        data = await self._store.async_load() or {}
        self.latest_message = data.get("latest_message") or {}
        self.message_count = int(data.get("message_count", 0))

    @callback
    def async_store_message(self, message_data: dict[str, Any]) -> None:
        """Record a received message and tell the entities."""
        self.latest_message = dict(message_data)
        self.message_count += 1
        self._store.async_delay_save(self._data_to_save, STORAGE_SAVE_DELAY)
        async_dispatcher_send(self.hass, SIGNAL_MESSAGE_STORED.format(self.entry_id))

    @callback
    def _data_to_save(self) -> dict[str, Any]:
        return {
            "latest_message": self.latest_message,
            "message_count": self.message_count,
        }

    async def async_flush(self) -> None:
        """Write now, cancelling any pending delayed save (entry unloading)."""
        await self._store.async_save(self._data_to_save())

    async def async_remove(self) -> None:
        """Delete the saved state (the config entry is being removed)."""
        await self._store.async_remove()
