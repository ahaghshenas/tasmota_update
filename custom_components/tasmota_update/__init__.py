"""Tasmota Update integration for Home Assistant."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from homeassistant.components.mqtt import async_publish
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import async_get as async_get_device_registry
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry
from homeassistant.helpers.event import async_track_time_interval

_LOGGER = logging.getLogger(__name__)

DOMAIN = "tasmota_update"
DEFAULT_CLEANUP_DAYS = 7
DEFAULT_GITHUB_REPO = "arendst/Tasmota"
CHECK_INTERVAL = timedelta(hours=1)


def _get_options(entry: ConfigEntry) -> dict:
    """Get options with defaults."""
    return {
        "cleanup_days": entry.options.get("cleanup_days", DEFAULT_CLEANUP_DAYS),
        "github_repo": entry.options.get("github_repo", DEFAULT_GITHUB_REPO),
    }


def _build_github_url(repo: str) -> str:
    """Build GitHub API URL from repo string."""
    return f"https://api.github.com/repos/{repo}/releases/latest"


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
            "last_seen": {},
        }

    # Give existing devices a grace period on startup
    _init_last_seen(hass)

    # Fetch the latest version on startup
    await _fetch_latest_version(hass)

    # Schedule periodic version checks
    cancel_interval = async_track_time_interval(
        hass, lambda _now: _fetch_latest_version(hass), CHECK_INTERVAL
    )
    entry.async_on_unload(cancel_interval)

    # Schedule periodic stale device cleanup
    cancel_cleanup = async_track_time_interval(
        hass, lambda _now: _cleanup_stale_devices(hass), timedelta(hours=1)
    )
    entry.async_on_unload(cancel_cleanup)

    # Listen for options changes
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    # Forward the setup to the update platform
    await hass.config_entries.async_forward_entry_setups(entry, ["update"])
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, ["update"])


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update — reload the integration."""
    old_repo = entry.options.get("github_repo", DEFAULT_GITHUB_REPO)
    await hass.config_entries.async_reload(entry.entry_id)
    new_entry = hass.config_entries.async_get_entry(entry.entry_id)
    if new_entry:
        new_repo = new_entry.options.get("github_repo", DEFAULT_GITHUB_REPO)
        if old_repo != new_repo:
            await _update_ota_urls(hass, new_repo)


async def _update_ota_urls(hass: HomeAssistant, github_repo: str) -> None:
    """Send OtaUrl command to all Tasmota devices when repo changes."""
    data = hass.data[DOMAIN]
    ota_url = f"https://github.com/{github_repo}/releases/latest/download/tasmota.bin.gz"

    for entity in data["entities"]:
        topic = (
            entity.full_topic
            .replace("%prefix%", "cmnd")
            .replace("%topic%", entity._device_topic)
            + "OtaUrl"
        )
        try:
            await async_publish(hass, topic, ota_url)
            _LOGGER.info("Set OtaUrl for %s: %s", entity.device_id, ota_url)
        except Exception:  # noqa: BLE001
            _LOGGER.warning("Failed to set OtaUrl for %s", entity.device_id, exc_info=True)


def _init_last_seen(hass: HomeAssistant) -> None:
    """Give existing Tasmota devices a grace period on startup."""
    data = hass.data[DOMAIN]
    device_registry = async_get_device_registry(hass)
    now = datetime.now(timezone.utc)

    for device in device_registry.devices.values():
        for identifier in device.identifiers:
            if identifier[0] == DOMAIN:
                device_mac = identifier[1]
                if device_mac not in data["last_seen"]:
                    data["last_seen"][device_mac] = now


def _cleanup_stale_devices(hass: HomeAssistant) -> None:
    """Remove Tasmota devices that haven't been seen for the configured period and have no entities."""
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    options = _get_options(entry)
    max_age = timedelta(days=options["cleanup_days"])

    data = hass.data[DOMAIN]
    last_seen = data.get("last_seen", {})
    device_registry = async_get_device_registry(hass)
    entity_registry = async_get_entity_registry(hass)

    now = datetime.now(timezone.utc)
    stale_devices: list[str] = []

    for device in device_registry.devices.values():
        for identifier in device.identifiers:
            if identifier[0] == DOMAIN:
                device_mac = identifier[1]
                seen = last_seen.get(device_mac)
                if seen is None:
                    continue
                if now - seen > max_age:
                    # Only remove if device has no entities at all
                    has_entities = any(
                        e.device_id == device.id
                        for e in entity_registry.entities.values()
                    )
                    if not has_entities:
                        stale_devices.append(device.id)
                        _LOGGER.debug(
                            "Stale device: %s (MAC: %s, last seen: %s)",
                            device.id, device_mac, seen.isoformat(),
                        )

    for device_id in stale_devices:
        device_registry.async_remove_device(device_id)
        _LOGGER.info("Removed stale Tasmota device: %s", device_id)

    if stale_devices:
        _LOGGER.info("Cleaned up %d stale Tasmota device(s)", len(stale_devices))


async def _fetch_latest_version(hass: HomeAssistant) -> None:
    """Fetch the latest Tasmota firmware version from GitHub."""
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    options = _get_options(entry)
    github_url = _build_github_url(options["github_repo"])

    latest_version = await async_get_latest_version(hass, github_url)
    if not latest_version:
        return

    _LOGGER.debug("Fetched latest Tasmota version: %s", latest_version)
    hass.data[DOMAIN]["latest_version"] = latest_version

    # Push the new version to all registered entities
    for entity in hass.data[DOMAIN]["entities"]:
        entity.set_latest_version(latest_version)


async def async_get_latest_version(hass: HomeAssistant, github_url: str) -> str | None:
    """Fetch the latest firmware version tag from GitHub, stripping the leading 'v'."""
    session = async_get_clientsession(hass)
    try:
        resp = await session.get(github_url, timeout=10)
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
