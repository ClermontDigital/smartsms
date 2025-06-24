# SmartSMS Integration for Home Assistant

[![HACS Badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)
[![GitHub Release](https://img.shields.io/github/release/ClermontDigital/smartsms.svg)](https://github.com/ClermontDigital/smartsms/releases)
[![License](https://img.shields.io/github/license/ClermontDigital/smartsms.svg)](LICENSE)

A powerful Home Assistant integration that receives inbound SMS messages via Twilio webhooks, exposes each message as entities, and enables sophisticated automation triggers for notifications, forwarding, and smart home responses.

## ✨ Features

- **📱 Real-time SMS Reception**: Receive SMS messages through Twilio webhooks with < 5s latency
- **🏠 Native HA Integration**: Exposes messages as sensors and binary sensors for automations
- **🎯 Smart Filtering**: Whitelist/blacklist senders and filter by keywords or regex patterns
- **🔔 Multiple Notifications**: Push to HA Companion app, forward to Signal, or trigger custom webhooks
- **🔒 Secure Processing**: HMAC signature validation and HTTPS-only webhooks
- **📊 Message Analytics**: Track message counts and maintain 6-month history via HA recorder
- **🚀 Event-Driven**: Rich event system for complex automation triggers

## 🚀 Quick Start

**Requirements:**
- Home Assistant 2024.1+ with external URL configured
- Twilio account with SMS-enabled phone number

**5-minute setup:**
1. Install SmartSMS via HACS (see installation below)
2. Add SmartSMS integration in HA, enter Twilio credentials
3. Copy webhook URL to Twilio phone number configuration  
4. Send test SMS - see message appear as `sensor.smartsms_last_message`
5. Create automation using `binary_sensor.smartsms_new_message` trigger

## 🏗️ Architecture

```
[SMS Provider] → POST /api/webhook/<id> → [SmartSMS Integration]
                                              ├─→ Updates sensor.smartsms_* entities  
                                              ├─→ Fires smartsms_message_received events
                                              └─→ Triggers automations & notifications
```

## 📦 Installation

### Method 1: HACS (Recommended)

1. Open HACS in Home Assistant
2. Go to **Integrations** → **⋮** → **Custom repositories**
3. Add repository URL: `https://github.com/ClermontDigital/smartsms`
4. Category: **Integration**
5. Search for "SmartSMS" and install
6. **Restart Home Assistant**

### Method 2: Manual Installation

1. Download the latest release from [GitHub Releases](https://github.com/ClermontDigital/smartsms/releases)
2. Extract and copy `custom_components/smartsms/` to your HA `custom_components/` directory
3. Restart Home Assistant
4. The integration will appear in **Settings** → **Devices & Services**

## ⚙️ Configuration

### 1. Home Assistant Setup

1. Go to **Settings** → **Devices & Services** → **Add Integration**
2. Search for "SmartSMS" and click to configure
3. Enter your Twilio credentials:
   - **Account SID**: From [Twilio Console](https://console.twilio.com/)
   - **Auth Token**: From Twilio Console (keep secure!)
4. Configure optional filters:
   - **Sender Whitelist**: Only process messages from these numbers (comma-separated)
   - **Sender Blacklist**: Ignore messages from these numbers  
   - **Keywords**: Trigger special events for these terms (supports `regex:pattern`)
5. **Copy the webhook URL** provided for Twilio configuration

### 2. Twilio Console Setup

1. Log into [Twilio Console](https://console.twilio.com/)
2. Navigate to **Phone Numbers** → **Manage** → **Active numbers**
3. Click your SMS-enabled phone number
4. In the **Messaging** section:
   - **Webhook URL**: Paste the URL from SmartSMS configuration
   - **HTTP Method**: `POST`
   - **Save Configuration**

### 3. Testing Your Setup

For testing with Twilio sandbox (recommended for first-time setup):
1. In Twilio Console, go to **Messaging** → **Try it out** → **Send an SMS**
2. Use the sandbox number and follow the SMS verification process
3. Send test messages to your sandbox number to verify the integration works

**First message checklist:**
- ✅ Webhook URL configured in Twilio
- ✅ SMS sent to your Twilio number
- ✅ Check HA **Developer Tools** → **Events** for `smartsms_message_received`
- ✅ Verify entities are created: `sensor.smartsms_last_message`, etc.

**Troubleshooting first setup:**
- Ensure your HA instance is accessible externally (check external URL in HA settings)
- Verify webhook URL is exactly what SmartSMS provided (including https://)
- Check HA logs for any SmartSMS errors

## 🎛️ Entities Created

Once configured, SmartSMS creates these entities:

### Sensors
- **`sensor.smartsms_last_message`** - Content of most recent SMS (truncated to 255 chars)
  - *Attributes*: `full_message`, `sender`, `timestamp`, `message_sid`, `to_number`, `provider`, `matched_keywords`
- **`sensor.smartsms_last_sender`** - Phone number of last sender
  - *Attributes*: `message_preview`, `timestamp`, `message_sid`, `to_number`, `provider`
- **`sensor.smartsms_message_count`** - Total messages received (auto-incrementing)
  - *Attributes*: `last_message_time`, `last_sender`, `provider`

### Binary Sensors  
- **`binary_sensor.smartsms_new_message`** - Triggers `ON` for 5 seconds on new messages
  - *Attributes*: `reset_delay`, `message_count`, `last_message_preview`, `last_sender`, `last_message_time`

## 🔥 Events for Automations

SmartSMS fires rich events for advanced automation triggers:

### `smartsms_message_received`
Fired for every received message with full payload:
```yaml
event_type: smartsms_message_received
data:
  sender: "+1234567890"
  body: "Your verification code is 123456"  
  timestamp: "2024-01-15T10:30:00"
  message_sid: "SMxxxxxxxxxxxxxxxxxxxxxxx"
  to_number: "+1987654321"
  provider: "twilio"
```

### `smartsms_keyword_matched`  
Fired when message contains configured keywords:
```yaml
event_type: smartsms_keyword_matched
data:
  sender: "+1234567890"
  body: "ALARM triggered in zone 3"
  matched_keywords: ["ALARM", "zone"]
  # ... same data as message_received
```

## 🤖 Automation Examples

### Basic SMS Notification
```yaml
automation:
  - alias: "Forward SMS to Mobile"
    trigger:
      - platform: state
        entity_id: binary_sensor.smartsms_new_message
        to: "on"
    action:
      - service: notify.mobile_app_your_phone
        data:
          title: "📱 New SMS"
          message: >
            From: {{ states('sensor.smartsms_last_sender') }}
            Message: {{ states('sensor.smartsms_last_message') }}
          data:
            importance: high
            channel: SMS
```

### Emergency Keyword Response
```yaml
automation:
  - alias: "Emergency SMS Alert"
    trigger:
      - platform: event
        event_type: smartsms_keyword_matched
    condition:
      - condition: template
        value_template: >
          {{ 'EMERGENCY' in trigger.event.data.matched_keywords or 
             'HELP' in trigger.event.data.matched_keywords }}
    action:
      - service: notify.all_devices
        data:
          title: "🚨 EMERGENCY SMS"
          message: >
            URGENT: {{ trigger.event.data.body }}
            From: {{ trigger.event.data.sender }}
          data:
            importance: max
            persistent: true
      - service: light.turn_on
        target:
          entity_id: light.all_lights
        data:
          color_name: red
          brightness: 255
```

### Verification Code Extraction  
```yaml
automation:
  - alias: "Extract Verification Codes"
    trigger:
      - platform: event
        event_type: smartsms_message_received
    condition:
      - condition: template
        value_template: >
          {{ trigger.event.data.body | regex_search('\\b\\d{4,8}\\b') }}
    action:
      - service: input_text.set_value
        target:
          entity_id: input_text.last_verification_code
        data:
          value: >
            {{ trigger.event.data.body | regex_findall('\\b\\d{4,8}\\b') | first }}
      - service: notify.persistent_notification
        data:
          title: "Verification Code"
          message: "Code saved: {{ states('input_text.last_verification_code') }}"
```

### Family Location Updates
```yaml
automation:
  - alias: "Family Home Notifications"
    trigger:
      - platform: event
        event_type: smartsms_keyword_matched
    condition:
      - condition: template
        value_template: >
          {{ 'home' in trigger.event.data.matched_keywords|map('lower')|list }}
    action:
      - service: person.set_location
        target:
          entity_id: >
            {% set phone = trigger.event.data.sender %}
            {% if phone == '+1234567890' %}person.john
            {% elif phone == '+1987654321' %}person.jane
            {% endif %}
        data:
          location: home
      - service: notify.family_group
        data:
          message: >
            {{ trigger.event.data.sender }} just arrived home!
```

## 🔧 Advanced Configuration

### Message Filtering Examples

**Whitelist specific family members:**
```
+1234567890, +1987654321, +1555000111
```

**Keywords with regex support:**
```
ALARM, EMERGENCY, CODE, regex:^Your.*code.*\d{6}
```

**Blacklist spam numbers:**
```  
+1800555, +1900, +15551234567
```

### Custom Webhook Forwarding
```yaml
automation:
  - alias: "Forward to Discord"
    trigger:
      - platform: event
        event_type: smartsms_message_received
    action:
      - service: rest_command.discord_webhook
        data:
          message: >
            **New SMS from {{ trigger.event.data.sender }}:**
            {{ trigger.event.data.body }}
```

## 🔒 Security & Privacy

- **HTTPS Only**: All webhooks require HTTPS connections
- **HMAC Verification**: Twilio signatures validated to prevent spoofing  
- **Encrypted Storage**: Twilio auth tokens encrypted in HA configuration
- **Local Processing**: All message processing happens locally in HA
- **6-Month Retention**: Messages stored in HA database for 6 months (configurable)
- **Optional Filtering**: Whitelist/blacklist for privacy control

## 🐛 Troubleshooting

### Common Issues

**Webhook not receiving messages:**
1. Verify webhook URL in Twilio console matches SmartSMS configuration
2. Check HA external URL is accessible from internet
3. Ensure firewall allows inbound HTTPS traffic
4. Test with Twilio sandbox numbers first

**Invalid signature errors:**  
1. Verify Auth Token is correct in HA configuration
2. Check webhook URL exactly matches (including HTTPS)
3. Restart HA after credential changes

**Messages not appearing:**
1. Check HA logs for SmartSMS errors: **Settings** → **System** → **Logs**
2. Verify message passes sender whitelist/blacklist filters
3. Test with simple message without special characters

### Debug Logging
Add to `configuration.yaml`:
```yaml
logger:
  logs:
    custom_components.smartsms: debug
```

## 🤝 Contributing

We welcome contributions! Please see our [Contributing Guidelines](CONTRIBUTING.md) for details.

### Development Setup
1. Fork the repository
2. Create feature branch: `git checkout -b feature/amazing-feature`
3. Make changes and test locally
4. Commit: `git commit -m 'Add amazing feature'`
5. Push: `git push origin feature/amazing-feature`
6. Open Pull Request

## 📋 Roadmap

- [ ] **Multi-Provider Support**: Sinch, MessageBird, AWS SNS
- [ ] **Two-Way SMS**: Send replies from HA automations  
- [ ] **Message Threading**: Conversation management
- [ ] **Auto-Discovery**: Detect and configure notification services
- [ ] **Analytics Dashboard**: Message statistics and trends
- [ ] **Template Responses**: Auto-reply with dynamic content

## 🆘 Support & Community

- **Issues**: [GitHub Issues](https://github.com/ClermontDigital/smartsms/issues)
- **Discussions**: [GitHub Discussions](https://github.com/ClermontDigital/smartsms/discussions)
- **Discord**: [Home Assistant Community](https://discord.gg/home-assistant)

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

**Made with ❤️ for the Home Assistant community** 