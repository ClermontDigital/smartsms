# SmartSMS Integration PRD

## Integration Name  
SmartSMS

## Product Requirements Document

### 1. Overview  
An official Home Assistant integration, SmartSMS, that receives inbound SMS via any SMS-as-a-Service provider webhook, exposes each message as an HA entity, and lets you trigger automations—sending push notifications to Home Assistant Companion app subscribers or forwarding content into Signal (or any other service).

### 2. Objectives  
- **Capture** inbound SMS via Home Assistant’s built-in webhook subscriber.  
- **Expose** each SMS as a sensor/entity in Home Assistant.  
- **Trigger** automations on new messages.  
- **Notify** nominated users via the HA Companion app or forward to Signal chat.  
- **Support** multiple SMS providers and output channels.

### 3. Goals & Success Metrics  
| Goal                                           | Success Metric                                  |
|------------------------------------------------|-------------------------------------------------|
| Reliable SMS ingestion                         | ≥ 95 % of SMS delivered in < 5 s                |
| Quick setup                                    | First message received within 10 min of install |
| Flexible notifications                         | Companion app & Signal working out-of-the-box   |
| Secure handling                                | All webhooks over HTTPS; optional HMAC verify   |

### 4. Use Cases  
1. **Personal Alerts**: Verification codes via SMS → trigger door unlock.  
2. **Family Notifications**: Kid texts “I’m home” → HA app notifies parents; updates presence.  
3. **Business Alerts**: Monitoring SMS → forward to Ops Signal channel + push.  
4. **Service Reminders**: Appointment SMS → auto-create calendar event + notify user.

### 5. User Stories  
- **US1**: As a homeowner, I want to see incoming SMS in HA so I don’t miss critical alerts.  
- **US2**: As an admin, I want to trigger automations on specific keywords (e.g. “ALARM”).  
- **US3**: As a team lead, I want SMS notifications forwarded into our Signal group chat.  
- **US4**: As a privacy-conscious user, I want to restrict which messages get stored in HA.

### 6. Functional Requirements  
1. **Integration Setup**  
   - Config flow to register SMS provider credentials and generate/select an HA webhook ID.  
   - UI options to whitelist senders or filter by keyword/regex.  
2. **Entity Exposure**  
   - `sensor.sms_last_message` → text of the most recent SMS.  
   - `sensor.sms_last_sender`  → sender phone number.  
   - `sensor.sms_timestamp`    → ISO timestamp of receipt.  
   - Optional history: last N messages as attributes or via a `sensor.sms_history` JSON list.  
3. **Webhook Subscriber**  
   - Leverage HA’s core webhook integration: provider posts to `/api/webhook/<webhook_id>`.  
   - Validate using HA’s webhook secret and optional HMAC header.  
4. **Filtering & Parsing**  
   - Configurable filters by sender, keyword, or regex.  
   - Optional payload parsing: extract codes, JSON fields, etc.  
5. **Notification Actions**  
   - Service `notify.sms_alert` for Companion app pushes.  
   - Built-in support for `notify.signal` (if installed).  
   - Generic “forward to HTTP” for custom webhooks or chat integrations.  
6. **Automation Triggers**  
   - Trigger on “new message” events.  
   - Trigger on “keyword match” events.  
   - Debounce/batch options (e.g. group messages within 10 s).

### 7. Non-Functional Requirements  
- **Performance**: Handle bursts up to 1 msg/s.  
- **Security**: Require HTTPS; support HMAC verification.  
- **Reliability**: Retry failed webhook deliveries up to 3 times.  
- **Maintainability**: Conform to HA integration guidelines; include unit & integration tests.  
- **Localization**: UI translatable into supported languages.

### 8. Architecture & Data Flow  
```text
[SMS Provider]
      └─ HTTP POST ──▶  /api/webhook/<webhook_id>  ──▶  [SmartSMS Integration]
                                                      ├─▶ updates `sensor.sms_*` entities  
                                                      └─▶ calls `notify.sms_alert` / forwards to Signal
