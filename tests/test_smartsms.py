"""Tests for the SmartSMS integration."""
from __future__ import annotations

import pytest
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import (
    async_capture_events,
    async_fire_time_changed,
)
from homeassistant.util import dt as dt_util
from homeassistant.util.aiohttp import MockRequest
from homeassistant.components import webhook as ha_webhook
from homeassistant.helpers import device_registry as dr
from datetime import timedelta
import json

from custom_components.smartsms.const import (
    CONF_DEFAULT_SENDER,
    CONF_KEYWORDS,
    CONF_SENDER_BLACKLIST,
    CONF_SENDER_WHITELIST,
    DOMAIN,
    EVENT_KEYWORD_MATCHED,
    EVENT_MESSAGE_RECEIVED,
)

from .conftest import WEBHOOK_ID

API = "https://api.mobilemessage.com.au/v1/messages"
OK = {"status": "complete", "results": [
    {"status": "success", "message_id": "abc-123", "to": "0400000001", "sender": "61400000000", "cost": 1}
]}


# ---------------------------------------------------------------- config flow

async def test_config_flow_shows_webhook_then_creates(hass):
    await hass.config.async_update(external_url="https://ha.example.com")
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "user"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {
        "name": "SmartSMS", "api_username": " User ", "api_password": "pw", "default_sender": "614111",
    })
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "webhook"
    assert result["description_placeholders"]["webhook_url"].startswith("https://ha.example.com/api/webhook/")
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["api_username"] == "User"
    assert result["data"]["webhook_id"]
    assert "webhook_secret" not in result["data"]

    # same account again is refused
    again = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    again = await hass.config_entries.flow.async_configure(again["flow_id"], {
        "name": "x", "api_username": "user", "api_password": "pw", "default_sender": "614111",
    })
    assert again["type"] is FlowResultType.ABORT and again["reason"] == "already_configured"


async def test_config_flow_requires_sender(hass):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {
        "name": "SmartSMS", "api_username": "u", "api_password": "p", "default_sender": "  ",
    })
    assert result["errors"] == {"default_sender": "sender_required"}


async def test_options_flow_saves_sender_and_filters(hass, loaded):
    result = await hass.config_entries.options.async_init(loaded.entry_id)
    assert result["step_id"] == "init"
    result = await hass.config_entries.options.async_configure(result["flow_id"], {
        CONF_DEFAULT_SENDER: " 61499999999 ",
        CONF_SENDER_WHITELIST: ["0400 000 001", " "],
        CONF_SENDER_BLACKLIST: [],
        CONF_KEYWORDS: ["gate", "regex:^code \\d+"],
    })
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert loaded.options == {
        CONF_DEFAULT_SENDER: "61499999999",
        CONF_SENDER_WHITELIST: ["0400 000 001"],
        CONF_SENDER_BLACKLIST: [],
        CONF_KEYWORDS: ["gate", "regex:^code \\d+"],
    }


# ---------------------------------------------------------------- sending

async def test_send_returns_response(hass, loaded, aioclient_mock):
    aioclient_mock.post(API, json=OK)
    resp = await hass.services.async_call(
        DOMAIN, "send_sms", {"to": "0400000001", "message": "hi", "custom_ref": "r1"},
        blocking=True, return_response=True,
    )
    assert resp == {"message_id": "abc-123", "to": "0400000001", "sender": "61400000000", "cost": 1}
    body = aioclient_mock.mock_calls[0][2]
    assert body == {"messages": [{"to": "0400000001", "message": "hi", "sender": "61400000000", "custom_ref": "r1"}]}


async def test_send_without_response_still_works(hass, loaded, aioclient_mock):
    aioclient_mock.post(API, json=OK)
    assert await hass.services.async_call(
        DOMAIN, "send_sms", {"to": "0400000001", "message": "hi"}, blocking=True
    ) is None


async def test_options_sender_wins_over_setup_sender(hass, loaded, aioclient_mock):
    hass.config_entries.async_update_entry(loaded, options={CONF_DEFAULT_SENDER: "61499999999"})
    aioclient_mock.post(API, json=OK)
    await hass.services.async_call(DOMAIN, "send_sms", {"to": "0400000001", "message": "hi"}, blocking=True)
    assert aioclient_mock.mock_calls[0][2]["messages"][0]["sender"] == "61499999999"


@pytest.mark.parametrize(("status", "payload", "match"), [
    (401, {"error": "unauthorised"}, "credentials"),
    (500, {"error": "boom"}, "HTTP 500"),
    (200, {"status": "complete", "results": [{"status": "error", "error": "Insufficient credit"}]}, "Insufficient credit"),
    (200, {"status": "failed"}, "failed"),
    (500, None, "HTTP 500"),
])
async def test_send_failures_raise(hass, loaded, aioclient_mock, status, payload, match):
    if payload is None:
        aioclient_mock.post(API, status=status, text="<html>oops</html>")
    else:
        aioclient_mock.post(API, status=status, json=payload)
    with pytest.raises(HomeAssistantError, match=match):
        await hass.services.async_call(DOMAIN, "send_sms", {"to": "0400000001", "message": "hi"}, blocking=True)


@pytest.mark.parametrize(("data", "match"), [
    ({"to": "12", "message": "hi"}, "not a valid phone number"),
    ({"to": "0400000001", "message": "   "}, "empty"),
    ({"to": "0400000001", "message": "x" * 766}, "maximum is 765"),
])
async def test_send_validation_raises(hass, loaded, aioclient_mock, data, match):
    with pytest.raises(ServiceValidationError, match=match):
        await hass.services.async_call(DOMAIN, "send_sms", data, blocking=True)
    assert aioclient_mock.call_count == 0


# ---------------------------------------------------------------- receiving

async def _post(hass, hass_client_no_auth, payload):
    client = await hass_client_no_auth()
    resp = await client.post(f"/api/webhook/{WEBHOOK_ID}", json=payload)
    await hass.async_block_till_done()
    return resp.status, await resp.text()


MSG = {"message": "Hi *Steve* & co_op!\nCall 0400 000 001 <now>", "sender": "61400000001",
       "to": "61400000000", "message_id": "m1", "received_at": "2026-09-24T10:00:00Z"}


async def test_inbound_sms_updates_entities_and_keeps_text(hass, loaded, hass_client_no_auth):
    events = async_capture_events(hass, EVENT_MESSAGE_RECEIVED)
    status, text = await _post(hass, hass_client_no_auth, MSG)
    assert (status, text) == (200, "OK")

    assert events[0].data["body"] == "Hi *Steve* & co_op!\nCall 0400 000 001 <now>"
    last = hass.states.get("sensor.smartsms_last_message")
    assert last.state == "Hi *Steve* & co_op! Call 0400 000 001 <now>"
    assert last.attributes["raw_message"] == events[0].data["body"]
    assert hass.states.get("sensor.smartsms_last_sender").state == "61400000001"
    assert hass.states.get("sensor.smartsms_message_count").state == "1"

    new = hass.states.get("binary_sensor.smartsms_new_message")
    assert new.state == "on" and "device_class" not in new.attributes
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=6))
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.smartsms_new_message").state == "off"


async def test_inbound_count_survives_reload(hass, loaded, hass_client_no_auth, hass_storage, freezer):
    await _post(hass, hass_client_no_auth, MSG)
    await _post(hass, hass_client_no_auth, MSG)
    freezer.tick(timedelta(seconds=11))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass_storage[f"{DOMAIN}.{loaded.entry_id}"]["data"]["message_count"] == 2

    assert await hass.config_entries.async_reload(loaded.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.smartsms_message_count").state == "2"
    assert hass.states.get("sensor.smartsms_last_sender").state == "61400000001"


async def test_inbound_filters_and_keywords(hass, loaded, hass_client_no_auth):
    hass.config_entries.async_update_entry(loaded, options={
        CONF_DEFAULT_SENDER: "61400000000",
        CONF_SENDER_WHITELIST: ["0400 000 001"],   # local form matches 614… sender
        CONF_SENDER_BLACKLIST: [],
        CONF_KEYWORDS: ["gate", "regex:code \\d{4}"],
    })
    await hass.async_block_till_done()
    kw = async_capture_events(hass, EVENT_KEYWORD_MATCHED)

    status, text = await _post(hass, hass_client_no_auth, {**MSG, "message": "Gate code 1234"})
    assert text == "OK"
    assert kw[0].data["matched_keywords"] == ["gate", "regex:code \\d{4}"]

    status, text = await _post(hass, hass_client_no_auth, {**MSG, "sender": "61499999999"})
    assert (status, text) == (200, "FILTERED")
    assert hass.states.get("sensor.smartsms_message_count").state == "1"


@pytest.mark.parametrize("payload", [{"sender": "614"}, {"message": "hi"}, ["list"], {"message": "  ", "sender": "1"}])
async def test_inbound_bad_payload(hass, loaded, hass_client_no_auth, payload):
    status, _ = await _post(hass, hass_client_no_auth, payload)
    assert status == 400
    assert hass.states.get("sensor.smartsms_message_count").state == "0"


async def test_inbound_text_is_not_rewritten(hass, loaded, hass_client_no_auth):
    events = async_capture_events(hass, EVENT_MESSAGE_RECEIVED)
    link = "https://t.example.com/?id=AB%2F12+3&x=%20"
    await _post(hass, hass_client_no_auth, {**MSG, "message": link})
    await _post(hass, hass_client_no_auth, {**MSG, "message": "x&notes Tom&times2 fish &amp; chips &#39;ok&#39;"})
    assert events[0].data["body"] == link
    assert events[1].data["body"] == "x&notes Tom&times2 fish & chips 'ok'"


async def test_inbound_too_large(hass, loaded, hass_client_no_auth):
    status, _ = await _post(hass, hass_client_no_auth, {**MSG, "message": "x" * 20000})
    assert status == 413


# ---------------------------------------------------------------- lifecycle

async def test_unload_removes_action_and_webhook(hass, loaded, hass_client_no_auth):
    assert hass.services.has_service(DOMAIN, "send_sms")
    assert await hass.config_entries.async_unload(loaded.entry_id)
    assert loaded.state is ConfigEntryState.NOT_LOADED
    assert not hass.services.has_service(DOMAIN, "send_sms")
    status, _ = await _post(hass, hass_client_no_auth, MSG)
    assert status == 200  # HA answers unknown webhooks with 200 and ignores them
    assert await hass.config_entries.async_setup(loaded.entry_id)


async def test_device_has_no_twilio_leftovers(hass, loaded):
    from homeassistant.helpers import device_registry as dr
    [device] = dr.async_entries_for_config_entry(dr.async_get(hass), loaded.entry_id)
    assert device.name == "SmartSMS"
    assert device.configuration_url == "https://mobilemessage.com.au/"
    assert "twilio" not in (device.model or "").lower()


async def test_diagnostics_redacts(hass, loaded, hass_client_no_auth):
    from custom_components.smartsms.diagnostics import async_get_config_entry_diagnostics
    hass.config_entries.async_update_entry(loaded, options={
        CONF_DEFAULT_SENDER: "61499999999", CONF_SENDER_WHITELIST: ["0400000001"],
    })
    await _post(hass, hass_client_no_auth, MSG)
    diag = await async_get_config_entry_diagnostics(hass, loaded)
    assert diag["data"]["api_password"] == "**REDACTED**"
    assert diag["data"]["webhook_id"] == "**REDACTED**"
    assert diag["options"][CONF_DEFAULT_SENDER] == "**REDACTED**"
    assert diag["data"][CONF_DEFAULT_SENDER] == "**REDACTED**"
    assert diag["sender_in_use_from"] == "options"
    assert diag["options_sender_differs_from_setup"] is True
    assert diag["options"][CONF_SENDER_WHITELIST] == "**REDACTED**"
    assert diag["latest_message"]["body"] == "**REDACTED**"
    assert diag["message_count"] == 1


# ---------------------------------------------------------------- review fixes

async def test_cloudhook_delivery_is_processed(hass, loaded):
    """Nabu Casa cloudhooks hand the handler a MockRequest (no content_length/read())."""
    events = async_capture_events(hass, EVENT_MESSAGE_RECEIVED)
    request = MockRequest(
        content=json.dumps(MSG).encode(), mock_source="cloud", method="POST",
        headers={"Content-Type": "application/json"},
    )
    response = await ha_webhook.async_handle_webhook(hass, WEBHOOK_ID, request)
    await hass.async_block_till_done()
    assert response.status == 200 and response.text == "OK"
    assert events[0].data["sender"] == "61400000001"
    assert hass.states.get("sensor.smartsms_message_count").state == "1"


async def test_cloudhook_oversized_is_refused(hass, loaded):
    request = MockRequest(content=json.dumps({**MSG, "message": "x" * 20000}).encode(),
                          mock_source="cloud", method="POST")
    response = await ha_webhook.async_handle_webhook(hass, WEBHOOK_ID, request)
    assert response.status == 413


async def test_options_url_is_never_the_lan_address(hass, loaded):
    await hass.config.async_update(internal_url="http://192.168.1.2:8123")
    result = await hass.config_entries.options.async_init(loaded.entry_id)
    url = result["description_placeholders"]["webhook_url"]
    assert "192.168" not in url and "no public URL" in url
    await hass.config.async_update(external_url="https://ha.example.com")
    result = await hass.config_entries.options.async_init(loaded.entry_id)
    assert result["description_placeholders"]["webhook_url"] == f"https://ha.example.com/api/webhook/{WEBHOOK_ID}"


async def test_options_form_falls_back_when_legacy_sender_empty(hass, loaded):
    hass.config_entries.async_update_entry(loaded, options={CONF_DEFAULT_SENDER: ""})
    result = await hass.config_entries.options.async_init(loaded.entry_id)
    schema = {str(k): k.default() for k in result["data_schema"].schema if hasattr(k, "default")}
    assert schema[CONF_DEFAULT_SENDER] == "61400000000"


async def test_reload_right_after_sms_keeps_count(hass, loaded, hass_client_no_auth, hass_storage, freezer):
    await _post(hass, hass_client_no_auth, MSG)
    await _post(hass, hass_client_no_auth, MSG)
    assert await hass.config_entries.async_reload(loaded.entry_id)  # before the 10 s save
    await hass.async_block_till_done()
    assert hass.states.get("sensor.smartsms_message_count").state == "2"
    await _post(hass, hass_client_no_auth, MSG)
    freezer.tick(timedelta(seconds=30))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass_storage[f"{DOMAIN}.{loaded.entry_id}"]["data"]["message_count"] == 3


async def test_remove_leaves_no_stored_messages(hass, loaded, hass_client_no_auth, hass_storage, freezer):
    await _post(hass, hass_client_no_auth, MSG)
    await hass.config_entries.async_remove(loaded.entry_id)
    freezer.tick(timedelta(seconds=30))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert f"{DOMAIN}.{loaded.entry_id}" not in hass_storage


async def test_unique_id_backfilled_for_legacy_entry(hass, loaded):
    assert loaded.unique_id == "user"
    again = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    again = await hass.config_entries.flow.async_configure(again["flow_id"], {
        "name": "x", "api_username": "USER", "api_password": "pw", "default_sender": "614111",
    })
    assert again["type"] is FlowResultType.ABORT


async def test_alphanumeric_senders_are_not_collapsed(hass, loaded, hass_client_no_auth):
    hass.config_entries.async_update_entry(loaded, options={
        CONF_DEFAULT_SENDER: "61400000000", CONF_SENDER_BLACKLIST: ["ALDI1", "0061 400 000 009"],
    })
    assert (await _post(hass, hass_client_no_auth, {**MSG, "sender": "Bank1"}))[1] == "OK"
    assert (await _post(hass, hass_client_no_auth, {**MSG, "sender": "aldi1"}))[1] == "FILTERED"
    assert (await _post(hass, hass_client_no_auth, {**MSG, "sender": "+61400000009"}))[1] == "FILTERED"


async def test_send_non_dict_json_raises_cleanly(hass, loaded, aioclient_mock):
    aioclient_mock.post(API, json=["unexpected"])
    with pytest.raises(HomeAssistantError, match="unexpected response"):
        await hass.services.async_call(DOMAIN, "send_sms", {"to": "0400000001", "message": "hi"}, blocking=True)


async def test_errors_do_not_echo_numbers(hass, loaded, aioclient_mock):
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(DOMAIN, "send_sms", {"to": "0400 12", "message": "hi"}, blocking=True)
    assert "0400 12" not in str(err.value)
    aioclient_mock.post(API, status=400, text="to=0400000001 message=secret")
    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(DOMAIN, "send_sms", {"to": "0400000001", "message": "hi"}, blocking=True)
    assert "secret" not in str(err.value) and "HTTP 400" in str(err.value)


async def test_diagnostics_when_not_loaded(hass, entry):
    from custom_components.smartsms.diagnostics import async_get_config_entry_diagnostics
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["message_count"] is None and diag["sender_in_use_from"] == "setup"


async def test_options_url_is_the_cloudhook_with_ha_cloud(hass, loaded):
    """With HA Cloud, the (existing or new) cloudhook is shown, not a /api/webhook URL."""
    import sys
    import types
    from unittest.mock import AsyncMock, patch
    fake = types.ModuleType("homeassistant.components.cloud")
    fake.async_active_subscription = lambda hass: True
    fake.async_get_or_create_cloudhook = AsyncMock(return_value="https://hooks.nabu.casa/abc")
    hass.config.components.add("cloud")
    with patch.dict(sys.modules, {"homeassistant.components.cloud": fake}):
        result = await hass.config_entries.options.async_init(loaded.entry_id)
    assert result["description_placeholders"]["webhook_url"] == "https://hooks.nabu.casa/abc"
    fake.async_get_or_create_cloudhook.assert_awaited_once_with(hass, WEBHOOK_ID)


async def test_diagnostics_options_only_sender_is_not_a_difference(hass):
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from custom_components.smartsms.diagnostics import async_get_config_entry_diagnostics
    entry = MockConfigEntry(domain=DOMAIN, title="SmartSMS",
                            data={"name": "SmartSMS", "api_username": "u", "api_password": "p", "webhook_id": "w"},
                            options={CONF_DEFAULT_SENDER: "61400000000"})
    entry.add_to_hass(hass)
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["sender_in_use_from"] == "options"
    assert diag["options_sender_differs_from_setup"] is False
