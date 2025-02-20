"""Initialize the Tasmota Update component."""
import logging
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.discovery import async_load_platform

_LOGGER = logging.getLogger(__name__)

DOMAIN = "tasmota_update"

async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Tasmota Update component."""
    _LOGGER.debug("Initializing Tasmota Update component")

    # Get the configuration for this component (if any)
    conf = config.get(DOMAIN, {})
    _LOGGER.debug(f"Configuration loaded: {conf}")

    # Pass an empty config to the platform setup
    hass.async_create_task(
        async_load_platform(
            hass, "update", DOMAIN, {}, config
        )
    )

    _LOGGER.debug("Tasmota Update component setup complete")
    return True