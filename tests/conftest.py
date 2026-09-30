"""Shared fixtures.

pytest-homeassistant-custom-component refuses to load anything from
custom_components/ unless `enable_custom_integrations` is requested, and its
own fixture is not autouse.
"""

from unittest.mock import MagicMock, patch

import pytest
from custom_components.cellar_tracker.const import DOMAIN
from homeassistant.const import CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME
from pytest_homeassistant_custom_component.common import MockConfigEntry
from tests.fixtures import SAMPLE_ROWS


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def mock_client():
    """Patch the CellarTracker class the coordinator instantiates.

    Configure behaviour through mock_client.return_value.get_inventory.
    """
    cls = MagicMock()
    cls.return_value.get_inventory.return_value = [dict(row) for row in SAMPLE_ROWS]
    with patch("custom_components.cellar_tracker.coordinator.CellarTracker", cls):
        yield cls


@pytest.fixture
def config_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Alice",
        unique_id="alice",
        data={CONF_USERNAME: "Alice", CONF_PASSWORD: "pw"},
        options={CONF_SCAN_INTERVAL: 3600},
    )
