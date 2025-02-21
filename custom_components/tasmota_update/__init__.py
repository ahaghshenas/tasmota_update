import logging
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)
DOMAIN = "tasmota_update"

async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Tasmota Update component."""
    _LOGGER.debug("Initializing Tasmota Update component")
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Tasmota Update from a config entry."""
    _LOGGER.debug("Setting up Tasmota Update from config entry")

    # Forward the setup to the update platform and await it
    await hass.config_entries.async_forward_entry_setups(entry, ["update"])
    return True