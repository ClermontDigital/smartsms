"""Data storage and management for SmartSMS integration."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant  # type: ignore
from homeassistant.util import dt as dt_util  # type: ignore

from .const import DEFAULT_MESSAGE_RETENTION_DAYS, DOMAIN

_LOGGER = logging.getLogger(__name__)


class SmartSMSDataStore:
    """Manages message storage and cleanup for SmartSMS integration."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Initialize the data store."""
        self.hass = hass
        self.entry_id = entry_id
        self._cleanup_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    def store_message(self, message_data: dict[str, Any]) -> None:
        """Store a new message and update counters."""
        try:
            # Get or create entry data
            entry_data = self._get_entry_data()
            
            # Update latest message
            entry_data["latest_message"] = message_data.copy()
            
            # Increment counter
            entry_data["message_count"] = entry_data.get("message_count", 0) + 1
            
            # Add to history with timestamp
            message_with_timestamp = {
                **message_data,
                "stored_at": dt_util.utcnow().isoformat(),
            }
            
            # Initialize history if not exists
            if "message_history" not in entry_data:
                entry_data["message_history"] = []
                
            entry_data["message_history"].append(message_with_timestamp)
            
            # Trigger cleanup if history is getting large
            if len(entry_data["message_history"]) > 1000:
                self._schedule_cleanup()
                
            _LOGGER.debug("Stored message from %s, total count: %d", 
                         message_data.get("sender", "unknown"), 
                         entry_data["message_count"])
                         
        except Exception as err:
            _LOGGER.error("Failed to store message: %s", err)

    def _get_entry_data(self) -> dict[str, Any]:
        """Get the data for this entry, creating if necessary."""
        if DOMAIN not in self.hass.data:
            self.hass.data[DOMAIN] = {}
            
        if self.entry_id not in self.hass.data[DOMAIN]:
            _LOGGER.warning("Entry data not found for %s, creating new", self.entry_id)
            self.hass.data[DOMAIN][self.entry_id] = {
                "config": {},
                "latest_message": {},
                "message_count": 0,
                "message_history": [],
            }
            
        return self.hass.data[DOMAIN][self.entry_id]

    def get_entry_data(self) -> dict[str, Any]:
        """Get the data for this entry."""
        return self.hass.data[DOMAIN].get(self.entry_id, {})

    def _schedule_cleanup(self) -> None:
        """Schedule cleanup of old messages."""
        if self._cleanup_task and not self._cleanup_task.done():
            return  # Already scheduled
        
        try:
            self._cleanup_task = self.hass.async_create_task(self._cleanup_old_messages())
        except Exception as err:
            _LOGGER.error("Failed to schedule cleanup: %s", err)

    async def _cleanup_old_messages(self) -> None:
        """Clean up messages older than retention period."""
        async with self._lock:
            try:
                cutoff_date = dt_util.utcnow() - timedelta(days=DEFAULT_MESSAGE_RETENTION_DAYS)
                entry_data = self._get_entry_data()
                
                message_history = entry_data.get("message_history", [])
                original_count = len(message_history)
                
                if original_count == 0:
                    return
                
                # Filter out old messages
                filtered_messages = []
                for msg in message_history:
                    stored_at_str = msg.get("stored_at")
                    if not stored_at_str:
                        # Keep messages without timestamp (legacy)
                        filtered_messages.append(msg)
                        continue
                        
                    try:
                        stored_at = datetime.fromisoformat(stored_at_str.replace('Z', '+00:00'))
                        if stored_at > cutoff_date:
                            filtered_messages.append(msg)
                    except (ValueError, TypeError) as e:
                        _LOGGER.debug("Failed to parse timestamp '%s': %s", stored_at_str, e)
                        # Keep messages with invalid timestamps
                        filtered_messages.append(msg)
                
                entry_data["message_history"] = filtered_messages
                
                cleaned_count = original_count - len(filtered_messages)
                if cleaned_count > 0:
                    _LOGGER.info("Cleaned up %d old messages for entry %s", 
                               cleaned_count, self.entry_id)
                    
            except Exception as err:
                _LOGGER.error("Error during message cleanup for entry %s: %s", 
                            self.entry_id, err)

    async def cleanup(self) -> None:
        """Clean up resources when entry is removed."""
        try:
            # Cancel cleanup task
            if self._cleanup_task and not self._cleanup_task.done():
                self._cleanup_task.cancel()
                try:
                    await self._cleanup_task
                except asyncio.CancelledError:
                    pass
                except Exception as err:
                    _LOGGER.debug("Cleanup task exception during cancellation: %s", err)
                    
            _LOGGER.debug("Data store cleanup completed for entry %s", self.entry_id)
            
        except Exception as err:
            _LOGGER.error("Error during data store cleanup: %s", err) 