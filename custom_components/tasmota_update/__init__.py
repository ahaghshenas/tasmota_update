"""Tasmota Update integration for Home Assistant."""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.components.mqtt import async_subscribe
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_interval

_LOGGER = logging.getLogger(__name__)

DOMAIN = "tasmota_update"
GITHUB_URL = "https://api.github.com/repos/arendst/Tasmota/releases/latest"
CHECK_INTERVAL = timedelta(hours=1)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Tasmota Update component."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Tasmota Update from a config entry."""
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {
            "entities": [],
            "discovered_devices": set(),
            "latest_version": None,
        }

    # Fetch the latest version on startup
    await _fetch_latest_version(hass)

    # Schedule periodic version checks
    cancel_interval = async_track_time_interval(
        hass, lambda _now: _fetch_latest_version(hass), CHECK_INTERVAL
    )
    entry.async_on_unload(cancel_interval)

    # Forward the setup to the update platform
    await hass.config_entries.async_forward_entry_setups(entry, ["update"])
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, ["update"])


async def _fetch_latest_version(hass: HomeAssistant) -> None:
    """Fetch the latest Tasmota firmware version from GitHub."""
    latest_version = await async_get_latest_version(hass)
    if not latest_version:
        return

    _LOGGER.debug("Fetched latest Tasmota version: %s", latest_version)
    hass.data[DOMAIN]["latest_version"] = latest_version

    # Push the new version to all registered entities
    for entity in hass.data[DOMAIN]["entities"]:
        entity.set_latest_version(latest_version)


async def async_get_latest_version(hass: HomeAssistant) -> str | None:
    """Fetch the latest firmware version tag from GitHub, stripping the leading 'v'."""
    session = async_get_clientsession(hass)
    try:
        resp = await session.get(GITHUB_URL, timeout=10)
        if resp.status == 200:
            data = await resp.json()
            tag = data.get("tag_name", "")
            return tag.lstrip("v") if tag else None
        _LOGGER.warning("GitHub API returned HTTP %s", resp.status)
    except TimeoutError:
        _LOGGER.warning("Timeout fetching latest Tasmota version from GitHub")
    except Exception:  # noqa: BLE001
        _LOGGER.warning("Error fetching latest Tasmota version", exc_info=True)
    return None
