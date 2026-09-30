"""Shared fixtures.

pytest-homeassistant-custom-component refuses to load anything from
custom_components/ unless `enable_custom_integrations` is requested, and its
own fixture is not autouse.
"""

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield
