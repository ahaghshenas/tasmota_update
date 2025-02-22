import logging
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.event import async_track_time_interval
import datetime

_LOGGER = logging.getLogger(__name__)
DOMAIN = "tasmota_update"

async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Tasmota Update component."""
    _LOGGER.debug("Initializing Tasmota Update component")
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Tasmota Update from a config entry."""
    _LOGGER.debug("Setting up Tasmota Update from config entry")

    # Initialize hass.data for the integration
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {"entities": [], "latest_version": None}

    # Fetch the latest version globally
    async def fetch_latest_version(_):
        latest_version = await async_get_latest_version(hass)
        if latest_version:
            _LOGGER.debug(f"Fetched global latest version: {latest_version}")
            hass.data[DOMAIN]["latest_version"] = latest_version
            # Notify all entities to update their states
            for entity in hass.data[DOMAIN]["entities"]:
                entity._latest_version = latest_version
                entity.schedule_update_ha_state()

    # Initial fetch
    await fetch_latest_version(None)

    # Schedule periodic updates (e.g., every hour)
    async_track_time_interval(hass, fetch_latest_version, datetime.timedelta(hours=1))

    # Forward the setup to the update platform
    await hass.config_entries.async_forward_entry_setups(entry, ["update"])
    return True


async def async_get_latest_version(hass):
    """Fetch the latest firmware version from GitHub."""
    url = "https://api.github.com/repos/arendst/Tasmota/releases/latest"
    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    latest_version = data.get("tag_name")
                    _LOGGER.debug(f"Fetched latest version from GitHub: {latest_version}")
                    return latest_version
                else:
                    _LOGGER.error(f"Failed to fetch latest version: HTTP {response.status}")
    except ImportError:
        _LOGGER.error("aiohttp library is not available. Please install it to fetch the latest firmware version.")
    except Exception as e:
        _LOGGER.error(f"Error fetching latest version: {e}")
    return None  # Return None if fetching fails