"""Config and options flow tests."""

from datetime import timedelta

import pytest
from cellartracker.errors import AuthenticationError, CannotConnect
from custom_components.cellar_tracker.const import DOMAIN
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType


async def _start_user_flow(hass: HomeAssistant):
    return await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})


async def test_user_flow_creates_entry(hass: HomeAssistant, mock_client):
    result = await _start_user_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "Alice", CONF_PASSWORD: "pw"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Alice"
    assert result["data"] == {CONF_USERNAME: "Alice", CONF_PASSWORD: "pw"}
    assert result["result"].unique_id == "alice"


async def test_user_flow_strips_username_whitespace(hass: HomeAssistant, mock_client):
    result = await _start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "  Alice ", CONF_PASSWORD: "pw"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Alice"
    assert result["data"][CONF_USERNAME] == "Alice"
    assert result["result"].unique_id == "alice"
    mock_client.assert_any_call("Alice", "pw")


async def test_user_flow_accepts_an_empty_cellar(hass: HomeAssistant, mock_client):
    mock_client.return_value.get_inventory.return_value = []

    result = await _start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "Alice", CONF_PASSWORD: "pw"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.parametrize(
    ("side_effect", "error"),
    [
        (AuthenticationError, "invalid_auth"),
        (CannotConnect, "cannot_connect"),
        (TimeoutError, "cannot_connect"),
        (RuntimeError, "unknown"),
    ],
)
async def test_user_flow_errors_then_recovers(hass: HomeAssistant, mock_client, side_effect, error):
    mock_client.return_value.get_inventory.side_effect = side_effect

    result = await _start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "Alice", CONF_PASSWORD: "bad"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}

    mock_client.return_value.get_inventory.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "Alice", CONF_PASSWORD: "pw"}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_second_user_flow_is_rejected(hass: HomeAssistant, mock_client, config_entry):
    config_entry.add_to_hass(hass)

    result = await _start_user_flow(hass)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def _setup(hass: HomeAssistant, entry) -> None:
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_reauth_updates_password(hass: HomeAssistant, mock_client, config_entry):
    await _setup(hass, config_entry)

    result = await config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "new-pw"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data == {CONF_USERNAME: "Alice", CONF_PASSWORD: "new-pw"}
    assert config_entry.unique_id == "alice"
    mock_client.assert_called_with("Alice", "new-pw")


async def test_reauth_wrong_password_shows_error(hass: HomeAssistant, mock_client, config_entry):
    await _setup(hass, config_entry)
    mock_client.return_value.get_inventory.side_effect = AuthenticationError

    result = await config_entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "still-wrong"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}
    assert config_entry.data[CONF_PASSWORD] == "pw"


async def test_options_flow_saves_interval_and_reloads(
    hass: HomeAssistant, mock_client, config_entry
):
    await _setup(hass, config_entry)
    assert mock_client.return_value.get_inventory.call_count == 1

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["step_id"] == "init"
    # Must differ from the current 3600: OptionsFlowWithReload only reloads
    # when the options actually change.
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCAN_INTERVAL: 600}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options == {CONF_SCAN_INTERVAL: 600}
    assert isinstance(config_entry.options[CONF_SCAN_INTERVAL], int)
    assert mock_client.return_value.get_inventory.call_count == 2
    assert config_entry.runtime_data.update_interval == timedelta(seconds=600)
