"""Fixtures for SmartSMS tests."""
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartsms.const import (
    CONF_API_PASSWORD,
    CONF_API_USERNAME,
    CONF_DEFAULT_SENDER,
    CONF_WEBHOOK_ID,
    DOMAIN,
)

WEBHOOK_ID = "test-webhook-id"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Load custom_components/ in every test."""
    yield


@pytest.fixture
def entry(hass) -> MockConfigEntry:
    """A config entry as created by 0.9.x (no options yet)."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="SmartSMS",
        data={
            "name": "SmartSMS",
            CONF_API_USERNAME: "user",
            CONF_API_PASSWORD: "pass",
            CONF_DEFAULT_SENDER: "61400000000",
            CONF_WEBHOOK_ID: WEBHOOK_ID,
            "webhook_secret": "legacy",
        },
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
async def loaded(hass, entry) -> MockConfigEntry:
    """The entry, set up."""
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry
