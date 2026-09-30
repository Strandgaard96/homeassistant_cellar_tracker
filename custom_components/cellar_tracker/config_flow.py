"""Config flow placeholder.

Home Assistant imports this module and needs a registered handler before it
sets up any config entry. The real flow steps are added in a later change.
"""

from homeassistant.config_entries import ConfigFlow

from .const import DOMAIN


class CellarTrackerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Placeholder handler; has no steps yet."""

    VERSION = 1
