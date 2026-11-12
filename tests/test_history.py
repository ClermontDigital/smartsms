"""Tests for the message history, contact names and the messages card's WebSocket API."""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import pytest
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
)

from custom_components.smartsms.const import DOMAIN, EVENT_MESSAGE_SENT

from .test_smartsms import API, MSG, OK, _post


async def _history(hass, hass_ws_client):
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "smartsms/history"})
    msg = await client.receive_json()
    assert msg["success"], msg
    return msg["result"]


async def test_received_and_sent_share_a_thread(
    hass, loaded, hass_client_no_auth, hass_ws_client, aioclient_mock, hass_admin_user
):
    await _post(hass, hass_client_no_auth, {**MSG, "sender": "61400000001", "message": "Gate is open"})
    aioclient_mock.post(API, json=OK)
    events = async_capture_events(hass, EVENT_MESSAGE_SENT)
    await hass.services.async_call(
        DOMAIN, "send_sms", {"to": "0400 000 001", "message": "Thanks!"},
        blocking=True, context=Context(user_id=hass_admin_user.id),
    )

    result = await _history(hass, hass_ws_client)
    received, sent = result["messages"]
    assert received["direction"] == "in" and received["body"] == "Gate is open"
    assert received["status"] == "received" and received["message_id"] == "m1"
    assert sent["direction"] == "out" and sent["body"] == "Thanks!" and sent["status"] == "sent"
    assert received["thread"] == sent["thread"] == "61400000001"
    assert sent["sent_by"] == hass_admin_user.name
    assert sent["message_id"] == "abc-123" and sent["cost"] == 1
    assert result["can_send"] is True and result["contacts"] == {}

    assert events[0].data == {"message_id": "abc-123", "to": "0400000001", "sender": "61400000000",
                              "cost": 1, "body": "Thanks!"}
    assert events[0].context.user_id == hass_admin_user.id


async def test_automation_sends_have_no_sender_name(hass, loaded, hass_ws_client, aioclient_mock):
    aioclient_mock.post(API, json=OK)
    await hass.services.async_call(DOMAIN, "send_sms", {"to": "0400000001", "message": "hi"}, blocking=True)
    [sent] = (await _history(hass, hass_ws_client))["messages"]
    assert sent["sent_by"] is None


async def test_failed_send_is_logged_and_still_raises(hass, loaded, hass_ws_client, aioclient_mock):
    aioclient_mock.post(API, json={"status": "complete", "results": [{"status": "error", "error": "Insufficient credit"}]})
    events = async_capture_events(hass, EVENT_MESSAGE_SENT)
    with pytest.raises(HomeAssistantError, match="Insufficient credit"):
        await hass.services.async_call(DOMAIN, "send_sms", {"to": "0400000001", "message": "hi"}, blocking=True)
    [failed] = (await _history(hass, hass_ws_client))["messages"]
    assert failed["status"] == "failed" and "Insufficient credit" in failed["error"]
    assert "message_id" not in failed
    assert not events


async def test_invalid_sends_are_not_logged(hass, loaded, hass_ws_client):
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "send_sms", {"to": "12", "message": "hi"}, blocking=True)
    assert (await _history(hass, hass_ws_client))["messages"] == []


async def test_history_is_admin_only(hass, loaded, hass_ws_client, hass_read_only_access_token):
    client = await hass_ws_client(hass, hass_read_only_access_token)
    for command in ({"type": "smartsms/history"}, {"type": "smartsms/subscribe"},
                    {"type": "smartsms/contact_set", "number": "0400000001", "name": "Al"}):
        await client.send_json_auto_id(command)
        msg = await client.receive_json()
        assert not msg["success"] and msg["error"]["code"] == "unauthorized"


async def test_subscribe_sends_now_and_on_change(hass, loaded, hass_client_no_auth, hass_ws_client):
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "smartsms/subscribe"})
    assert (await client.receive_json())["success"]
    first = await client.receive_json()
    assert first["type"] == "event" and first["event"]["messages"] == []

    await _post(hass, hass_client_no_auth, MSG)
    update = await client.receive_json()
    assert [m["body"] for m in update["event"]["messages"]] == [MSG["message"]]


async def test_contacts_are_named_by_number(hass, loaded, hass_ws_client, hass_storage, freezer):
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "smartsms/contact_set", "number": "0400 000 001", "name": "  Al   Smith "})
    msg = await client.receive_json()
    assert msg["result"] == {"thread": "61400000001", "name": "Al Smith"}
    assert (await _history(hass, hass_ws_client))["contacts"] == {"61400000001": "Al Smith"}

    await client.send_json_auto_id({"type": "smartsms/contact_set", "number": "+61400000001"})
    assert (await client.receive_json())["success"]
    assert (await _history(hass, hass_ws_client))["contacts"] == {}

    await client.send_json_auto_id({"type": "smartsms/contact_set", "number": "  ", "name": "x"})
    assert (await client.receive_json())["error"]["code"] == "invalid_format"


async def test_history_and_contacts_survive_reload(hass, loaded, hass_client_no_auth, hass_ws_client):
    await _post(hass, hass_client_no_auth, MSG)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "smartsms/contact_set", "number": "61400000001", "name": "Al"})
    await client.receive_json()
    assert await hass.config_entries.async_reload(loaded.entry_id)  # before the delayed save
    await hass.async_block_till_done()
    result = await _history(hass, hass_ws_client)
    assert len(result["messages"]) == 1 and result["contacts"] == {"61400000001": "Al"}


async def test_store_from_1_0_starts_history_with_latest(hass, entry, hass_ws_client, hass_storage):
    hass_storage[f"{DOMAIN}.{entry.entry_id}"] = {
        "version": 1, "key": f"{DOMAIN}.{entry.entry_id}",
        "data": {"latest_message": {"body": "Old one", "sender": "61400000009", "timestamp": "2026-09-24T10:00:00+00:00",
                                    "message_sid": "m0"}, "message_count": 2},
    }
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    [old] = (await _history(hass, hass_ws_client))["messages"]
    assert old["body"] == "Old one" and old["thread"] == "61400000009" and old["direction"] == "in"
    assert hass.states.get("sensor.smartsms_message_count").state == "2"


async def test_history_keeps_the_newest(hass, loaded, hass_ws_client):
    with patch("custom_components.smartsms.data_store.HISTORY_MAX", 3):
        store = loaded.runtime_data
        for n in range(5):
            store.async_log_sent("0400000001", f"m{n}", sender="s", sent_by=None, result={})
    assert [m["body"] for m in (await _history(hass, hass_ws_client))["messages"]] == ["m2", "m3", "m4"]


async def test_two_entries_merge_in_time_order(hass, loaded, hass_ws_client):
    other = MockConfigEntry(domain=DOMAIN, title="Second", unique_id="other", data={
        "name": "Second", "api_username": "other", "api_password": "p", "default_sender": "61400000000",
        "webhook_id": "second-hook",
    })
    other.add_to_hass(hass)
    assert await hass.config_entries.async_setup(other.entry_id)
    await hass.async_block_till_done()
    loaded.runtime_data.async_store_message({"body": "late", "sender": "1", "timestamp": "2026-09-24T12:00:00+10:00"})
    other.runtime_data.async_store_message({"body": "early", "sender": "2", "timestamp": "2026-09-24T01:00:00+00:00"})
    other.runtime_data.async_store_message({"body": "latest", "sender": "2", "timestamp": "2026-09-24T03:00:00+00:00"})
    assert [m["body"] for m in (await _history(hass, hass_ws_client))["messages"]] == ["early", "late", "latest"]


async def test_diagnostics_count_history_without_contents(hass, loaded, hass_client_no_auth, hass_ws_client):
    from custom_components.smartsms.diagnostics import async_get_config_entry_diagnostics
    await _post(hass, hass_client_no_auth, MSG)
    diag = await async_get_config_entry_diagnostics(hass, loaded)
    assert diag["history_count"] == 1 and diag["contact_count"] == 0
    assert "history" not in diag and MSG["message"] not in str(diag)


async def test_history_saved_after_delay(hass, loaded, hass_client_no_auth, hass_storage, freezer):
    await _post(hass, hass_client_no_auth, MSG)
    freezer.tick(timedelta(seconds=11))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    saved = hass_storage[f"{DOMAIN}.{loaded.entry_id}"]["data"]
    assert [m["body"] for m in saved["history"]] == [MSG["message"]] and saved["contacts"] == {}


async def test_card_is_served(hass, loaded, hass_client):
    client = await hass_client()
    resp = await client.get("/smartsms/smartsms-messages-card.js")
    assert resp.status == 200
    assert "smartsms-messages-card" in await resp.text()
