"""Config entry setup, unload and registry continuity."""

from cellartracker.errors import AuthenticationError, CannotConnect
from custom_components.cellar_tracker.const import DOMAIN
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import DOMAIN as HOMEASSISTANT_DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component


async def _setup(hass: HomeAssistant, entry) -> None:
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_setup_creates_entities(hass: HomeAssistant, mock_client, config_entry):
    await _setup(hass, config_entry)

    assert config_entry.state is ConfigEntryState.LOADED
    assert hass.states.get("sensor.cellar_tracker_total_bottles").state == "5"
    assert hass.states.get("sensor.cellar_tracker_country_france") is not None
    assert hass.states.get("sensor.cellar_tracker_by_producer") is not None
    mock_client.assert_called_once_with("Alice", "pw")


async def test_friendly_names_are_unchanged(hass: HomeAssistant, mock_client, config_entry):
    await _setup(hass, config_entry)

    state = hass.states.get("sensor.cellar_tracker_total_bottles")
    assert state.attributes["friendly_name"] == "Cellar Tracker total bottles"


async def test_entities_belong_to_one_service_device(
    hass: HomeAssistant, mock_client, config_entry
):
    await _setup(hass, config_entry)

    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, config_entry.entry_id)})
    assert device is not None
    assert device.name == "Cellar Tracker"
    assert device.entry_type is dr.DeviceEntryType.SERVICE
    entity = er.async_get(hass).async_get("sensor.cellar_tracker_total_bottles")
    assert entity.device_id == device.id


async def test_cannot_connect_retries_setup(hass: HomeAssistant, mock_client, config_entry):
    mock_client.return_value.get_inventory.side_effect = CannotConnect

    await _setup(hass, config_entry)

    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_unload(hass: HomeAssistant, mock_client, config_entry):
    await _setup(hass, config_entry)

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.NOT_LOADED


async def test_yaml_era_entity_is_adopted_with_its_entity_id(
    hass: HomeAssistant, mock_client, config_entry
):
    registry = er.async_get(hass)
    old = registry.async_get_or_create(
        "sensor", DOMAIN, "cellar_tracker_total_bottles", suggested_object_id="my_bottles"
    )
    assert old.entity_id == "sensor.my_bottles"
    assert old.config_entry_id is None

    await _setup(hass, config_entry)

    adopted = registry.async_get("sensor.my_bottles")
    assert adopted is not None
    assert adopted.config_entry_id == config_entry.entry_id
    assert hass.states.get("sensor.my_bottles").state == "5"
    assert hass.states.get("sensor.cellar_tracker_total_bottles") is None


async def test_stale_yaml_era_entity_is_removed(hass: HomeAssistant, mock_client, config_entry):
    registry = er.async_get(hass)
    stale = registry.async_get_or_create("sensor", DOMAIN, "cellar_tracker_country_narnia")

    await _setup(hass, config_entry)

    assert registry.async_get(stale.entity_id) is None


async def test_auth_failure_starts_reauth(hass: HomeAssistant, mock_client, config_entry):
    mock_client.return_value.get_inventory.side_effect = AuthenticationError

    await _setup(hass, config_entry)

    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert [flow["context"]["source"] for flow in flows] == [SOURCE_REAUTH]


async def test_yaml_block_is_rejected_with_repair_issue(hass: HomeAssistant, mock_client):
    yaml = {DOMAIN: {CONF_USERNAME: "Alice", CONF_PASSWORD: "pw"}}

    assert await async_setup_component(hass, DOMAIN, yaml)
    await hass.async_block_till_done()

    assert hass.config_entries.async_entries(DOMAIN) == []
    mock_client.assert_not_called()
    issue = ir.async_get(hass).async_get_issue(HOMEASSISTANT_DOMAIN, f"config_entry_only_{DOMAIN}")
    assert issue is not None
    assert issue.severity is ir.IssueSeverity.ERROR
