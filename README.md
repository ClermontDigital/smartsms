# SmartSMS - SMS Integration for Home Assistant

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![HACS Badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)
[![Version](https://img.shields.io/badge/version-0.9.9-green.svg)](https://github.com/ClermontDigital/smartsms)

Two-way SMS integration for Home Assistant using [Mobile Message API](https://mobilemessage.com.au/). Receive SMS via real-time webhooks and send SMS using the API.

## Features

- 📱 **Receive SMS** - Real-time webhooks via Home Assistant Cloud
- 📤 **Send SMS** - `smartsms.send_sms` service with phone number validation
- 🔧 **Entities** - Last message, sender, count, and new message sensors
- 🎯 **Filtering** - Whitelist/blacklist senders, keyword matching
- 🚀 **Events** - Fire automations on message received or keyword matched

## Quick Setup

### Requirements
- Home Assistant 2024.1+
- [Mobile Message account](https://mobilemessage.com.au/) with API credentials
- Home Assistant Cloud (Nabu Casa) for webhooks

### Installation
1. **HACS**: Add custom repository `https://github.com/ClermontDigital/smartsms`
2. **Manual**: Download and extract to `/config/custom_components/smartsms/`
3. Restart Home Assistant
4. Add integration via Settings → Devices & Services

### Configuration
1. **Get Mobile Message Credentials:**
   - **API Username/Password**: Found in account settings
   - **Sender ID**: Login to Mobile Message → **Settings → Sender IDs** → Use one of your approved numbers (e.g., `61480807776`)

2. **Add SmartSMS Integration:**
   - Enter API credentials and sender ID
   - Copy webhook URL to Mobile Message dashboard

3. **Test SMS Sending:**
   - Use Developer Tools → Actions → `smartsms.send_sms`

## Usage

### Entities Created
- `sensor.smartsms_last_message` - Latest SMS content
- `sensor.smartsms_last_sender` - Last sender phone number
- `sensor.smartsms_message_count` - Total messages received
- `binary_sensor.smartsms_new_message` - ON for 5 seconds when SMS arrives

### Send SMS Service
```yaml
service: smartsms.send_sms
data:
  to: "+61412345678"
  message: "Hello from Home Assistant!"
  sender: "MyCompany"  # Optional
```

### Sending SMS Examples

**Developer Tools - Actions:**
1. Go to Developer Tools → Actions
2. Choose `smartsms.send_sms`
3. Fill in the form:
   - **To**: `+61412345678`
   - **Message**: `Test message from Home Assistant`
   - **Sender**: `MyHome` (optional)

**In Automations:**
```yaml
# Simple notification
- service: smartsms.send_sms
  data:
    to: "+61412345678"
    message: "Door unlocked at {{ now().strftime('%H:%M') }}"

# With dynamic content
- service: smartsms.send_sms
  data:
    to: "{{ states('input_text.emergency_contact') }}"
    message: >
      Alert: {{ trigger.to_state.attributes.friendly_name }} 
      changed to {{ trigger.to_state.state }}
    custom_ref: "alert_{{ now().timestamp() }}"

# Multiple recipients (use repeat action)
- repeat:
    for_each:
      - "+61412345678"
      - "+61498765432"
    sequence:
      - service: smartsms.send_sms
        data:
          to: "{{ repeat.item }}"
          message: "Family alert: Everyone home safe!"
```

### Basic Automation Examples

**Notify on new SMS:**
```yaml
automation:
  - alias: "SMS Received"
    trigger:
      - platform: state
        entity_id: binary_sensor.smartsms_new_message
        to: "on"
    action:
      - service: notify.mobile_app_phone
        data:
          message: "SMS from {{ states('sensor.smartsms_last_sender') }}: {{ states('sensor.smartsms_last_message') }}"
```

**Send alarm notification:**
```yaml
automation:
  - alias: "Alarm Alert"
    trigger:
      - platform: state
        entity_id: alarm_control_panel.home
        to: "triggered"
    action:
      - service: smartsms.send_sms
        data:
          to: "+61412345678"
          message: "🚨 Home alarm triggered!"
```

## API Documentation

- [Mobile Message API Docs](https://mobilemessage.com.au/api-documentation)
- [Send SMS Endpoint](https://mobilemessage.com.au/api-documentation#send-sms-messages)
- [Webhook Configuration](https://mobilemessage.com.au/api-documentation#webhooks)

## Troubleshooting

- **No messages arriving**: Check webhook URL in Mobile Message settings matches Home Assistant Cloud webhook URL
- **Can't send SMS**: Verify Mobile Message account has credits and sender ID is registered
- **Integration not loading**: Restart Home Assistant after installation

Enable debug logging:
```yaml
logger:
  logs:
    custom_components.smartsms: debug
```

## Contributing

Bug reports and feature requests welcome via [GitHub Issues](https://github.com/ClermontDigital/smartsms/issues).

## License

MIT License - see [LICENSE](LICENSE) file for details. 