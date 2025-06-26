# SmartSMS - SMS Integration for Home Assistant

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![HACS Badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)
[![Version](https://img.shields.io/badge/version-0.9.3-green.svg)](https://github.com/ClermontDigital/smartsms)

A Home Assistant integration that receives and sends SMS messages via Mobile Message API. Receives messages through real-time webhooks and sends messages using the Mobile Message SMS API. Designed to work with Home Assistant Cloud (Nabu Casa) webhooks for reliable two-way SMS communication.

## What It Does

- **Receives SMS** messages through Mobile Message webhook API (real-time)
- **Sends SMS** messages using the `smartsms.send_sms` service
- **Creates entities** in Home Assistant with message content and sender info
- **Triggers automations** when new messages arrive
- **Filters messages** by sender or keywords if needed
- **Stores message history** for a configurable period
- **Works with Nabu Casa** for reliable webhook delivery

## Quick Start

### Requirements
- Home Assistant 2024.1 or newer  
- **Twilio account** with SMS-capable phone number
- Internet connectivity for API polling

### Installation

**Method 1: HACS (Recommended)**

1. **Add Custom Repository**:
   - Open HACS in Home Assistant
   - Go to **Integrations**
   - Click the **⋮** menu → **Custom repositories**
   - Add repository URL: `https://github.com/ClermontDigital/smartsms`
   - Category: **Integration**
   - Click **Add**

2. **Install SmartSMS**:
   - Find "SmartSMS" in HACS integrations
   - Click **Download**
   - Restart Home Assistant

3. **Add Integration**:
   - Go to Settings → Devices & Services → **Add Integration**
   - Search for "SmartSMS"
   - Enter your Twilio credentials

**Method 2: Manual**
1. Download the latest release from GitHub
2. Extract to `/config/custom_components/smartsms/`
3. Restart Home Assistant
4. Add the integration via Settings → Devices & Services

### Configuration

1. **Get Twilio Credentials**:
   - Account SID (starts with `AC...`, 34 characters)
   - Auth Token (32 characters, found under Account SID)

2. **Add Integration**:
   - Go to Settings → Devices & Services → Add Integration
   - Search for "SmartSMS"
   - Enter your Twilio credentials
   - Configure any message filters (optional)

3. **Test**:
   - Send an SMS to your Twilio phone number
   - Check that entities update within 60 seconds
   - Messages are polled automatically - no webhook setup needed

## How It Works

SmartSMS uses **Twilio API polling** instead of webhooks to retrieve messages:

- **Polls every 60 seconds** for new inbound messages
- **Tracks processed messages** to avoid duplicates
- **Applies filters** and fires Home Assistant events
- **Updates entities** with latest message data
- **No webhook configuration** required

This approach bypasses the known issues with Twilio webhooks and Home Assistant Cloud content-type handling.

## Entities Created

- **`sensor.smartsms_last_message`** - Content of the most recent SMS
- **`sensor.smartsms_last_sender`** - Phone number of the last sender  
- **`sensor.smartsms_message_count`** - Total messages received
- **`binary_sensor.smartsms_new_message`** - Turns ON for 5 seconds when a new message arrives

## Events

- **`smartsms_message_received`** - Fired for every message with full details
- **`smartsms_keyword_matched`** - Fired when configured keywords are detected

## Sending SMS

The integration provides a `smartsms.send_sms` service for sending SMS messages:

### Service Parameters
- **`to`** (required): Phone number to send to (e.g., `+61412345678` or `0412345678`)
- **`message`** (required): SMS content (maximum 765 characters)
- **`sender`** (optional): Sender ID - uses default sender if not specified
- **`custom_ref`** (optional): Custom reference for tracking

### Example Usage
```yaml
service: smartsms.send_sms
data:
  to: "+61412345678"
  message: "Hello from Home Assistant!"
  sender: "MyCompany"
  custom_ref: "notification_123"
```

### Setup Requirements
1. Configure a **Default Sender ID** during setup (optional but recommended)
2. Ensure your Mobile Message account has SMS sending credits
3. Your sender ID must be registered with Mobile Message (or use your phone number)

## Automation Examples

### Basic New Message Trigger
```yaml
automation:
  - alias: "SMS Received"
    trigger:
      - platform: state
        entity_id: binary_sensor.smartsms_new_message
        to: "on"
    action:
      - service: notify.mobile_app_your_phone
        data:
          title: "New SMS"
          message: "From {{ states('sensor.smartsms_last_sender') }}: {{ states('sensor.smartsms_last_message') }}"
```

### Keyword Detection
```yaml
automation:
  - alias: "Emergency SMS"
    trigger:
      - platform: event
        event_type: smartsms_keyword_matched
    condition:
      - condition: template
        value_template: "{{ 'EMERGENCY' in trigger.event.data.matched_keywords }}"
    action:
      - service: notify.all_devices
        data:
          title: "🚨 Emergency SMS"
          message: "{{ trigger.event.data.body }}"
```

### Extract Verification Codes
```yaml
automation:
  - alias: "Save Verification Code"
    trigger:
      - platform: event
        event_type: smartsms_message_received
    condition:
      - condition: template
        value_template: "{{ trigger.event.data.body | regex_search('\\b\\d{4,8}\\b') }}"
    action:
      - service: input_text.set_value
        target:
          entity_id: input_text.latest_verification_code
        data:
          value: "{{ trigger.event.data.body | regex_findall('\\b\\d{4,8}\\b') | first }}"
```

### Send SMS Notification
```yaml
automation:
  - alias: "Send SMS Alert"
    trigger:
      - platform: state
        entity_id: alarm_control_panel.home
        to: "triggered"
    action:
      - service: smartsms.send_sms
        data:
          to: "+61412345678"
          message: "🚨 Home alarm triggered at {{ now().strftime('%Y-%m-%d %H:%M') }}"
          custom_ref: "alarm_{{ now().timestamp() }}"
```

### Auto-reply to SMS
```yaml
automation:
  - alias: "SMS Auto-reply"
    trigger:
      - platform: event
        event_type: smartsms_message_received
    condition:
      - condition: template
        value_template: "{{ 'status' in trigger.event.data.body.lower() }}"
    action:
      - service: smartsms.send_sms
        data:
          to: "{{ trigger.event.data.sender }}"
          message: "Home Assistant status: All systems operational. Temperature: {{ states('sensor.temperature') }}°C"
```

### Forward SMS to Signal
```yaml
automation:
  - alias: "Forward SMS to Signal"
    description: "Automatically forward all incoming SMS messages to Signal"
    mode: single
    max_exceeded: silent
    trigger:
      - platform: event
        event_type: smartsms_message_received
    condition: []
    action:
      - service: persistent_notification.create
        data:
          title: "SMS Debug"
          message: "Automation triggered for SMS from {{ trigger.event.data.sender }}: {{ trigger.event.data.body }}"
      - service: notify.signal
        data:
          message: |
            📱 SMS from {{ trigger.event.data.sender }}:
            
            {{ trigger.event.data.body }}
          target:
            - "+1234567890"  # Replace with your Signal number
      - delay:
          seconds: 2
```

## Message Filtering

During setup, you can configure:

- **Sender Whitelist**: Only process messages from specific numbers
- **Sender Blacklist**: Ignore messages from specific numbers  
- **Keywords**: Watch for specific words or phrases (supports regex with `regex:pattern`)

## SMS Provider Setup

### Mobile Message
1. Create account at [mobilemessage.com.au](https://mobilemessage.com.au/)
2. Get a dedicated SMS number (free with account)
3. Configure webhook URL in account settings
4. Use API Username and Password in SmartSMS

### Finding Mobile Message Credentials
- **API Username**: Found in account settings
- **API Password**: Found in account settings
- **Webhook Setup**: Configure your HA webhook URL in Mobile Message dashboard

### Webhook Configuration
The integration expects Mobile Message webhook payload format:
- `message` - message content
- `sender` - sender number  
- `to` - receiving number
- `message_id` - unique message ID
- `received_at` - ISO timestamp

## Troubleshooting

### Messages Not Arriving

1. **Check Nabu Casa**: Ensure you have an active Home Assistant Cloud subscription
2. **Find webhook URL**: Go to Settings → Home Assistant Cloud → Webhooks to find your SmartSMS webhook URL
3. **Check SMS provider**: Make sure the webhook URL is configured correctly in your SMS provider
4. **Check logs**: Look for SmartSMS errors in Home Assistant logs
5. **Test webhook**: Send a test SMS to your number to verify the complete flow

### Common Issues

- **"Integration not loading"**: Restart Home Assistant after installation
- **"Webhook not found"**: Check that the URL matches exactly what's in your SMS provider settings
- **"No messages appearing"**: Verify your message filters aren't blocking everything

### Debug Logging
```yaml
logger:
  logs:
    custom_components.smartsms: debug
```

## Contributing

Bug reports and feature requests are welcome! Please use GitHub Issues.

For code contributions:
1. Fork the repository
2. Create a feature branch  
3. Make your changes
4. Submit a pull request

## License

MIT License - see [LICENSE](LICENSE) file for details. 