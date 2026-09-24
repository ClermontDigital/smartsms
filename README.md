# SmartSMS - SMS Integration for Home Assistant

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![HACS Badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)
[![Version](https://img.shields.io/badge/version-1.0.0-green.svg)](https://github.com/ClermontDigital/smartsms)

Two-way SMS integration for Home Assistant using [Mobile Message API](https://mobilemessage.com.au/). Receive SMS via real-time webhooks and send SMS using the API.

## Features

- 📱 **Receive SMS** - Real-time webhooks via Home Assistant Cloud
- 📤 **Send SMS** - `smartsms.send_sms` action; raises an error if Mobile Message doesn't accept the message, and can return the message ID and cost
- 🔧 **Entities** - Last message, sender, count, and new message sensors (kept across restarts)
- 🎯 **Filtering** - Allow/block lists of senders and keyword matching, set under **Configure**
- 🚀 **Events** - Fire automations on message received or keyword matched

## Quick Setup

### Requirements
- Home Assistant 2024.6+
- [Mobile Message account](https://mobilemessage.com.au/) with API credentials
- A public URL for webhooks: Home Assistant Cloud (a Cloud webhook is created for you) or your own external URL

### Installation
1. **HACS**: Add custom repository `https://github.com/ClermontDigital/smartsms`
2. **Manual**: Download and extract to `/config/custom_components/smartsms/`
3. Restart Home Assistant
4. Add integration via Settings → Devices & Services

### Configuration
1. **Get Mobile Message Credentials:**
   - **API Username/Password**: Found in account settings
   - **Sender ID**: Login to Mobile Message → **Settings → Sender IDs** → Use one of your approved numbers (e.g., `61412345678`)

2. **Add SmartSMS Integration:**
   - Enter API credentials and sender ID
   - The next screen shows your webhook URL; paste it into Mobile Message's inbound webhook settings
   - Change the sender ID, filters or keywords later with the integration's **Configure** button (it shows the webhook URL again)

3. **Test SMS Sending:**
   - Use Developer Tools → Actions → `smartsms.send_sms`

## Usage

### Events
- `smartsms_message_received` — every accepted SMS; data: `body`, `sender`, `to_number`, `timestamp`, `message_sid`, `provider`
- `smartsms_keyword_matched` — same data (both events carry `matched_keywords` when a keyword matched)

Message text is passed through as received, line breaks included (complete HTML entities such as `&amp;` are decoded); entity states are the one-line form.

### Upgrading from 0.9.x
- `smartsms.send_sms` now **fails** when Mobile Message doesn't send the message (it used to log and carry on). Add `continue_on_error: true` to the step if the rest of an automation should run regardless.
- A sender ID saved under **Configure** is now actually used (0.9.x ignored it).
- Event `body` is no longer stripped of `_`, `*` and backticks or flattened to one line.
- The `smartsms_data_updated` event is gone, and `binary_sensor.smartsms_new_message` reacts to real SMS only, not to a hand-fired `smartsms_message_received` event.

### Entities Created
- `sensor.smartsms_last_message` - Latest SMS content
- `sensor.smartsms_last_sender` - Last sender phone number
- `sensor.smartsms_message_count` - Total messages received
- `binary_sensor.smartsms_new_message` - ON for 5 seconds when SMS arrives

### Send SMS Action
```yaml
action: smartsms.send_sms
data:
  to: "+61412345678"
  message: "Hello from Home Assistant!"
  sender: "MyCompany"  # Optional
```

If Mobile Message rejects the message (bad credentials, no credit, unknown sender ID) the action fails
with that error, so automations can catch it with `continue_on_error` or show it in the trace.
Add `response_variable` to get the result:

```yaml
- action: smartsms.send_sms
  data:
    to: "0412345678"
    message: "Gate opened"
  response_variable: sms
- action: logbook.log
  data:
    name: SMS
    message: "Sent {{ sms.message_id }} ({{ sms.cost }} credits)"
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
- action: smartsms.send_sms
  data:
    to: "+61412345678"
    message: "Door unlocked at {{ now().strftime('%H:%M') }}"

# With dynamic content
- action: smartsms.send_sms
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
      - action: smartsms.send_sms
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
      - action: notify.mobile_app_phone
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
      - action: smartsms.send_sms
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
- **Checking settings**: Settings → Devices & Services → SmartSMS → ⋮ → Download diagnostics (credentials, numbers and message text are redacted)

Enable debug logging:
```yaml
logger:
  logs:
    custom_components.smartsms: debug
```

## Contributing

Bug reports and feature requests welcome via [GitHub Issues](https://github.com/ClermontDigital/smartsms/issues).

## License

Apache License 2.0 - see [LICENSE](LICENSE) file for details. 