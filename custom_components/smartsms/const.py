"""Constants for the SmartSMS integration."""
from __future__ import annotations

from typing import Final

DOMAIN: Final = "smartsms"

# Configuration keys
CONF_API_USERNAME: Final = "api_username"
CONF_API_PASSWORD: Final = "api_password"
CONF_WEBHOOK_ID: Final = "webhook_id"
CONF_DEFAULT_SENDER: Final = "default_sender"
CONF_SENDER_WHITELIST: Final = "sender_whitelist"
CONF_SENDER_BLACKLIST: Final = "sender_blacklist"
CONF_KEYWORDS: Final = "keywords"

# SMS sending
SERVICE_SEND_SMS: Final = "send_sms"
MM_API_BASE_URL: Final = "https://api.mobilemessage.com.au"
MM_SEND_ENDPOINT: Final = "/v1/messages"
MAX_MESSAGE_LENGTH: Final = 765
SEND_TIMEOUT: Final = 30  # seconds

# Entity keys
SENSOR_LAST_MESSAGE: Final = "last_message"
SENSOR_LAST_SENDER: Final = "last_sender"
SENSOR_MESSAGE_COUNT: Final = "message_count"
BINARY_SENSOR_NEW_MESSAGE: Final = "new_message"

# Event types
EVENT_MESSAGE_RECEIVED: Final = "smartsms_message_received"
EVENT_KEYWORD_MATCHED: Final = "smartsms_keyword_matched"

# Internal dispatcher signal, formatted with the config entry id
SIGNAL_MESSAGE_STORED: Final = "smartsms_message_stored_{}"

# Storage
STORAGE_VERSION: Final = 1
STORAGE_SAVE_DELAY: Final = 10  # seconds

# Limits
BINARY_SENSOR_RESET_DELAY: Final = 5  # seconds
SENSOR_STATE_MAX_LENGTH: Final = 255  # HA rejects longer states
INBOUND_BODY_MAX_LENGTH: Final = 1000
WEBHOOK_MAX_BYTES: Final = 10000

# Mobile Message webhook payload keys
MM_MESSAGE: Final = "message"
MM_SENDER: Final = "sender"
MM_TO: Final = "to"
MM_MESSAGE_ID: Final = "message_id"
MM_RECEIVED_AT: Final = "received_at"

# Attributes
ATTR_SENDER: Final = "sender"
ATTR_BODY: Final = "body"
ATTR_TIMESTAMP: Final = "timestamp"
ATTR_MESSAGE_SID: Final = "message_sid"
ATTR_TO_NUMBER: Final = "to_number"
ATTR_PROVIDER: Final = "provider"
ATTR_MATCHED_KEYWORDS: Final = "matched_keywords"
