"""Data storage and management for SmartSMS integration."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import DEFAULT_MESSAGE_RETENTION_DAYS, DOMAIN

_LOGGER = logging.getLogger(__name__)


class SmartSMSDataStore:
    """Manages message storage and cleanup for SmartSMS integration."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Initialize the data store."""
        self.hass = hass
        self.entry_id = entry_id
        self._cleanup_task: asyncio.Task | None = None
        
        # Initialize data structure
        if DOMAIN not in self.hass.data:
            self.hass.data[DOMAIN] = {}
        
        if entry_id not in self.hass.data[DOMAIN]:
            self.hass.data[DOMAIN][entry_id] = {
                "config": {},
                "latest_message": {},
                "message_count": 0,
                "message_history": [],
            }

    def store_message(self, message_data: dict[str, Any]) -> None:
        """Store a new message and update counters."""
        entry_data = self.hass.data[DOMAIN][self.entry_id]
        
        # Update latest message
        entry_data["latest_message"] = message_data
        
        # Increment counter
        entry_data["message_count"] = entry_data.get("message_count", 0) + 1
        
        # Add to history with timestamp
        message_with_timestamp = {
            **message_data,
            "stored_at": dt_util.utcnow().isoformat(),
        }
        entry_data["message_history"].append(message_with_timestamp)
        
        # Trigger cleanup if history is getting large
        if len(entry_data["message_history"]) > 1000:
            self._schedule_cleanup()

    def get_entry_data(self) -> dict[str, Any]:
        """Get the data for this entry."""
        return self.hass.data[DOMAIN].get(self.entry_id, {})

    def _schedule_cleanup(self) -> None:
        """Schedule cleanup of old messages."""
        if self._cleanup_task and not self._cleanup_task.done():
            return  # Already scheduled
        
        self._cleanup_task = asyncio.create_task(self._cleanup_old_messages())

    async def _cleanup_old_messages(self) -> None:
        """Clean up messages older than retention period."""
        try:
            cutoff_date = dt_util.utcnow() - timedelta(days=DEFAULT_MESSAGE_RETENTION_DAYS)
            entry_data = self.hass.data[DOMAIN][self.entry_id]
            
            original_count = len(entry_data["message_history"])
            
            # Filter out old messages
            entry_data["message_history"] = [
                msg for msg in entry_data["message_history"]
                if datetime.fromisoformat(msg.get("stored_at", "")) > cutoff_date
            ]
            
            cleaned_count = original_count - len(entry_data["message_history"])
            if cleaned_count > 0:
                _LOGGER.info("Cleaned up %d old messages for entry %s", cleaned_count, self.entry_id)
                
        except Exception as err:
            _LOGGER.error("Error during message cleanup: %s", err)

    def cleanup(self) -> None:
        """Clean up resources when entry is removed."""
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel() 