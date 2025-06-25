# SmartSMS - SMS Integration for Home Assistant

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![HACS Badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)
[![Version](https://img.shields.io/badge/version-0.7.1-green.svg)](https://github.com/ClermontDigital/smartsms)

A simple Home Assistant integration that receives SMS messages via webhooks and exposes them as entities for automation. Currently supports SMS providers that use webhook delivery.

## What It Does

- **Receives SMS** messages through webhook endpoints
- **Creates entities** in Home Assistant with message content and sender info
- **Triggers automations** when new messages arrive
- **Filters messages** by sender or keywords if needed
- **Stores message history** for a configurable period

## Quick Start

### Requirements
- Home Assistant 2024.1 or newer  
- **Home Assistant Cloud (Nabu Casa) subscription** - Required for webhook handling
- SMS provider with webhook support (tested with Twilio)

### Installation

**Method 1: HACS (Recommended)**
1. Add this repository to HACS as a custom integration
2. Install "SmartSMS" from HACS
3. Restart Home Assistant
4. Add the integration via Settings → Devices & Services

**Method 2: Manual**
1. Download the latest release
2. Extract to `/config/custom_components/smartsms/`
3. Restart Home Assistant
4. Add the integration via Settings → Devices & Services

### Configuration

1. **Get SMS Provider Credentials** (Twilio example):
   - Account SID (starts with `AC...`)
   - Auth Token (32 characters)

2. **Add Integration**:
   - Go to Settings → Devices & Services → Add Integration
   - Search for "SmartSMS"
   - Enter your provider credentials
   - Configure any message filters (optional)

3. **Set Up Webhook**:
   - After configuring the integration, go to Settings → Home Assistant Cloud → Webhooks
   - Find your SmartSMS webhook in the list and copy its URL
   - Configure this URL in your SMS provider's settings  
   - Send a test message to verify it works

**Note**: SmartSMS uses Home Assistant Cloud's webhook routing system, which requires an active Nabu Casa subscription. The webhook URLs are managed centrally in the cloud section, not within the integration itself.

## Entities Created

- **`sensor.smartsms_last_message`** - Content of the most recent SMS
- **`sensor.smartsms_last_sender`** - Phone number of the last sender  
- **`sensor.smartsms_message_count`** - Total messages received
- **`binary_sensor.smartsms_new_message`** - Turns ON for 5 seconds when a new message arrives

## Events

- **`smartsms_message_received`** - Fired for every message with full details
- **`smartsms_keyword_matched`** - Fired when configured keywords are detected

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

## Message Filtering

During setup, you can configure:

- **Sender Whitelist**: Only process messages from specific numbers
- **Sender Blacklist**: Ignore messages from specific numbers  
- **Keywords**: Watch for specific words or phrases (supports regex with `regex:pattern`)

## SMS Provider Setup

### Twilio
1. Create account at console.twilio.com
2. Buy a phone number
3. Configure webhook URL in phone number settings
4. Use Account SID and Auth Token in SmartSMS

### Finding Twilio Credentials
- **Account SID**: Main dashboard "Account Info" box, starts with `AC...` (34 characters)
- **Auth Token**: Click "eye" icon to reveal (32 characters)  
- **Alternative**: Console → Account → API keys & tokens

### Other Providers
Any SMS provider that can send POST requests to webhooks should work. The integration expects these fields in the webhook payload:
- `Body` - message content
- `From` - sender number
- `To` - receiving number
- `MessageSid` - unique message ID (optional)

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