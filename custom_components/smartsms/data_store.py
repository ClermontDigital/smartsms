"""Persistent storage for received messages, the message history and contact names."""
from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util
from homeassistant.util.ulid import ulid_now

from .const import (
    ATTR_BODY,
    ATTR_MESSAGE_SID,
    ATTR_SENDER,
    ATTR_TIMESTAMP,
    DOMAIN,
    HISTORY_MAX,
    SIGNAL_HISTORY_UPDATED,
    SIGNAL_MESSAGE_STORED,
    STORAGE_SAVE_DELAY,
    STORAGE_VERSION,
)
from .webhook import normalise_number


class SmartSMSDataStore:
    """The latest received message, the running count, the message history (in and
    out) and contact names, kept across restarts.

    The history and contacts are only handed out by the admin-only WebSocket API
    (api.py), never as entity attributes, which every Home Assistant user can read.
    """

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Initialize the data store."""
        self.hass = hass
        self.entry_id = entry_id
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}"
        )
        self.latest_message: dict[str, Any] = {}
        self.message_count: int = 0
        self.history: list[dict[str, Any]] = []  # oldest first
        self.contacts: dict[str, str] = {}  # normalised number -> name

    async def async_load(self) -> None:
        """Load the saved state, if there is any."""
        data = await self._store.async_load() or {}
        self.latest_message = data.get("latest_message") or {}
        self.message_count = int(data.get("message_count", 0))
        self.contacts = {
            k: v for k, v in (data.get("contacts") or {}).items() if isinstance(v, str) and v
        }
        if "history" in data:
            self.history = [m for m in data["history"] if isinstance(m, dict)][-HISTORY_MAX:]
        elif self.latest_message:
            # Saved by 1.0.x, which kept the latest message only: start the history with it
            self.history = [_received_record(self.latest_message)]

    @callback
    def async_store_message(self, message_data: dict[str, Any]) -> None:
        """Record a received message and tell the entities and the messages card."""
        self.latest_message = dict(message_data)
        self.message_count += 1
        self._add(_received_record(message_data))
        async_dispatcher_send(self.hass, SIGNAL_MESSAGE_STORED.format(self.entry_id))

    @callback
    def async_log_sent(
        self,
        to_number: str,
        body: str,
        *,
        sender: str,
        sent_by: str | None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        """Record a message sent (or that Mobile Message didn't accept)."""
        record: dict[str, Any] = {
            "id": ulid_now(),
            "direction": "out",
            "number": to_number,
            "thread": normalise_number(to_number),
            "body": body,
            "timestamp": dt_util.utcnow().isoformat(),
            "status": "failed" if error else "sent",
            "sender": sender,
            "sent_by": sent_by,
        }
        if result:
            record["message_id"] = result.get("message_id") or ""
            record["cost"] = result.get("cost")
        if error:
            record["error"] = error
        self._add(record)

    @callback
    def async_set_contact(self, thread: str, name: str) -> None:
        """Name a (normalised) number; an empty name forgets it."""
        if name == self.contacts.get(thread, ""):
            return
        if name:
            self.contacts[thread] = name
        else:
            del self.contacts[thread]
        self._changed()

    @callback
    def _add(self, record: dict[str, Any]) -> None:
        self.history.append(record)
        del self.history[:-HISTORY_MAX]
        self._changed()

    @callback
    def _changed(self) -> None:
        self._store.async_delay_save(self._data_to_save, STORAGE_SAVE_DELAY)
        async_dispatcher_send(self.hass, SIGNAL_HISTORY_UPDATED)

    @callback
    def _data_to_save(self) -> dict[str, Any]:
        return {
            "latest_message": self.latest_message,
            "message_count": self.message_count,
            "history": self.history,
            "contacts": self.contacts,
        }

    async def async_flush(self) -> None:
        """Write now, cancelling any pending delayed save (entry unloading)."""
        await self._store.async_save(self._data_to_save())

    async def async_remove(self) -> None:
        """Delete the saved state (the config entry is being removed)."""
        await self._store.async_remove()


def _received_record(message: dict[str, Any]) -> dict[str, Any]:
    """A received message as a history record."""
    sender = str(message.get(ATTR_SENDER) or "")
    return {
        "id": ulid_now(),
        "direction": "in",
        "number": sender,
        "thread": normalise_number(sender),
        "body": message.get(ATTR_BODY, ""),
        "timestamp": message.get(ATTR_TIMESTAMP) or dt_util.utcnow().isoformat(),
        "status": "received",
        "message_id": message.get(ATTR_MESSAGE_SID, ""),
    }
