"""Constants for the SmartSMS integration."""
from __future__ import annotations

from typing import Final

DOMAIN: Final = "smartsms"

# Configuration keys
CONF_ACCOUNT_SID: Final = "account_sid"
CONF_AUTH_TOKEN: Final = "auth_token"
CONF_WEBHOOK_ID: Final = "webhook_id"
CONF_WEBHOOK_SECRET: Final = "webhook_secret"
CONF_SENDER_WHITELIST: Final = "sender_whitelist"
CONF_SENDER_BLACKLIST: Final = "sender_blacklist"
CONF_KEYWORDS: Final = "keywords"

# Entity names
SENSOR_LAST_MESSAGE: Final = "last_message"
SENSOR_LAST_SENDER: Final = "last_sender"
SENSOR_MESSAGE_COUNT: Final = "message_count"
BINARY_SENSOR_NEW_MESSAGE: Final = "new_message"

# Event types
EVENT_MESSAGE_RECEIVED: Final = "smartsms_message_received"
EVENT_KEYWORD_MATCHED: Final = "smartsms_keyword_matched"

# Defaults
DEFAULT_WEBHOOK_SECRET_LENGTH: Final = 32
DEFAULT_MESSAGE_RETENTION_DAYS: Final = 180  # 6 months
BINARY_SENSOR_RESET_DELAY: Final = 5  # seconds

# Twilio webhook payload keys
TWILIO_BODY: Final = "Body"
TWILIO_FROM: Final = "From"
TWILIO_TO: Final = "To"
TWILIO_MESSAGE_SID: Final = "MessageSid"
TWILIO_ACCOUNT_SID: Final = "AccountSid"
TWILIO_TIMESTAMP: Final = "DateSent"

# Attributes
ATTR_SENDER: Final = "sender"
ATTR_BODY: Final = "body"
ATTR_TIMESTAMP: Final = "timestamp"
ATTR_MESSAGE_SID: Final = "message_sid"
ATTR_TO_NUMBER: Final = "to_number"
ATTR_PROVIDER: Final = "provider"
ATTR_MATCHED_KEYWORDS: Final = "matched_keywords" 