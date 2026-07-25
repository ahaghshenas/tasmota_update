"""Tasmota Update platform — MQTT discovery-based firmware update entities."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.components.mqtt import async_publish, async_subscribe
from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

_LOGGER = logging.getLogger(__name__)

DOMAIN = "tasmota_update"
GRACE_PERIOD = timedelta(minutes=5)
STATUS2_TIMEOUT = 5

# Tasmota hardware string → firmware binary name
# Keys are stripped of trailing version info (e.g. "ESP32-C3 v0.4" → "ESP32-C3")
_HARDWARE_TO_FIRMWARE: dict[str, str] = {
    "ESP8266": "tasmota",
    "ESP8266EX": "tasmota",
    "ESP8285": "tasmota",
    "ESP8285H16": "tasmota",
    "ESP32": "tasmota32",
    "ESP32-C3": "tasmota32c3",
    "ESP32-C6": "tasmota32c6",
    "ESP32-S2": "tasmota32s2",
    "ESP32-S3": "tasmota32s3",
}


def _make_lwt_handler(entity: TasmotaUpdateEntity, hass: HomeAssistant):
    """Return a callback that handles LWT messages for a specific entity."""

    def _handler(msg) -> None:
        payload = msg.payload
        _LOGGER.debug("LWT for %s: %s", entity.device_id, payload)

        if payload == "Online":
            entity._attr_available = True
        elif payload == "Offline" and not entity._in_progress and not entity._is_in_grace_period():
            entity._attr_available = False

        hass.loop.call_soon_threadsafe(entity.async_write_ha_state)

    return _handler


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tasmota Update entities from MQTT Discovery."""
    data = hass.data[DOMAIN]
    discovered: set[str] = data["discovered_devices"]
    github_repo = entry.options.get("github_repo", "arendst/Tasmota")

    async def _on_discovery(msg) -> None:
        """Handle incoming Tasmota MQTT Discovery messages."""
        if not msg.topic.endswith("/config"):
            return

        try:
            payload = json.loads(msg.payload)
        except json.JSONDecodeError:
            _LOGGER.warning("Invalid JSON on %s", msg.topic)
            return

        device_id = msg.topic.split("/")[-2]

        # Track when this device was last seen
        data["last_seen"][device_id] = datetime.now(timezone.utc)

        # --- Existing device: update firmware version or full_topic ----------
        for entity in data["entities"]:
            if entity.device_id == device_id:
                _update_existing_entity(entity, payload)
                # Query hardware if ota_firmware is still unknown
                if not entity._ota_firmware:
                    hass.async_create_task(_query_device_hardware(hass, entity, payload))
                return

        # --- New device -----------------------------------------------------
        if device_id in discovered:
            return
        discovered.add(device_id)

        entity = _build_entity(hass, device_id, payload, data["latest_version"], github_repo)
        async_add_entities([entity])
        data["entities"].append(entity)

        lwt_topic = _build_lwt_topic(payload, device_id)
        await async_subscribe(hass, lwt_topic, _make_lwt_handler(entity, hass))
        _LOGGER.debug(
            "Discovered %s — firmware %s, LWT on %s",
            device_id, payload.get("sw", "?"), lwt_topic,
        )

        # Query exact hardware type via Status 2
        hass.async_create_task(_query_device_hardware(hass, entity, payload))

    await async_subscribe(hass, "tasmota/discovery/#", _on_discovery)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_lwt_topic(payload: dict, device_id: str) -> str:
    """Construct the LWT topic from a Tasmota discovery payload."""
    full_topic = payload.get("ft", f"%prefix%/%topic%/")
    device_topic = payload.get("t", device_id)
    return full_topic.replace("%prefix%", "tele").replace("%topic%", device_topic) + "LWT"


async def _query_device_hardware(
    hass: HomeAssistant,
    entity: TasmotaUpdateEntity,
    payload: dict,
) -> None:
    """Query device hardware type via MQTT Status 2 and set ota_firmware.

    First checks the 'of' field from the discovery payload.
    If missing, sends Status 2 command and parses the Hardware field
    to determine the exact firmware binary name.
    """
    # First: check if discovery payload already has 'of'
    of = payload.get("of")
    if of:
        entity._ota_firmware = of
        entity.async_write_ha_state()
        _LOGGER.debug("Got ota_firmware from discovery for %s: %s", entity.device_id, of)
        return

    # Fallback: query device via MQTT Status 2
    full_topic = payload.get("ft", f"%prefix%/%topic%/")
    if not full_topic.endswith("/"):
        full_topic += "/"
    device_topic = payload.get("t", entity.device_id)

    cmnd_topic = full_topic.replace("%prefix%", "cmnd").replace("%topic%", device_topic) + "Status"
    stat_topic = full_topic.replace("%prefix%", "stat").replace("%topic%", device_topic) + "STATUS2"

    result_event = asyncio.Event()
    received_data: dict = {}

    async def _on_status_response(msg) -> None:
        try:
            received_data.update(json.loads(msg.payload))
        except json.JSONDecodeError:
            pass
        result_event.set()

    unsub = await async_subscribe(hass, stat_topic, _on_status_response)
    try:
        _LOGGER.debug(
            "Querying hardware from %s — cmnd: %s, stat: %s",
            entity.device_id, cmnd_topic, stat_topic,
        )
        await async_publish(hass, cmnd_topic, "2")
        try:
            await asyncio.wait_for(result_event.wait(), timeout=STATUS2_TIMEOUT)
        except asyncio.TimeoutError:
            _LOGGER.warning(
                "Timeout querying hardware from %s — set OtaUrl manually if needed",
                entity.device_id,
            )
            return

        hardware = received_data.get("StatusFWR", {}).get("Hardware", "")
        if not hardware:
            _LOGGER.warning("No Hardware field in Status 2 response from %s", entity.device_id)
            return

        # Strip trailing version info — e.g. "ESP32-C3 v0.4" → "ESP32-C3"
        hw_base = hardware.split(" v")[0].strip()

        ota_firmware = _HARDWARE_TO_FIRMWARE.get(hw_base)
        if ota_firmware:
            entity._ota_firmware = ota_firmware
            entity.async_write_ha_state()
            _LOGGER.info("Detected hardware for %s: %s → %s", entity.device_id, hw_base, ota_firmware)
        else:
            _LOGGER.warning(
                "Unknown hardware '%s' (base: '%s') for %s — cannot determine firmware binary",
                hardware, hw_base, entity.device_id,
            )
    finally:
        unsub()


def _build_entity(
    hass: HomeAssistant,
    device_id: str,
    payload: dict,
    latest_version: str | None,
    github_repo: str = "arendst/Tasmota",
) -> TasmotaUpdateEntity:
    """Create a TasmotaUpdateEntity from a discovery payload."""
    device_name = payload.get("dn", "") or device_id
    return TasmotaUpdateEntity(
        hass=hass,
        device_id=device_id,
        device_name=device_name,
        firmware_version=payload.get("sw", "unknown"),
        device_topic=payload.get("t", device_id),
        full_topic=payload.get("ft", f"%prefix%/%topic%/"),
        latest_version=latest_version,
        device_ip=payload.get("ip"),
        github_repo=github_repo,
        ota_firmware=payload.get("of"),
    )


def _update_existing_entity(entity: TasmotaUpdateEntity, payload: dict) -> None:
    """Push new discovery data into an already-created entity."""
    new_full_topic = payload.get("ft", f"%prefix%/%topic%/")
    if entity.full_topic != new_full_topic:
        _LOGGER.info(
            "full_topic changed for %s: %s -> %s",
            entity.device_id, entity.full_topic, new_full_topic,
        )
        entity.full_topic = new_full_topic

    firmware = payload.get("sw", "unknown")
    entity.firmware_version = firmware

    # Update ota_firmware if discovery provides it, or re-query if still unknown
    of = payload.get("of")
    if of:
        entity._ota_firmware = of
    elif not entity._ota_firmware:
        hass = entity.hass
        hass.async_create_task(_query_device_hardware(hass, entity, payload))

    # Mark update complete if firmware changed from pre-update version
    if entity._in_progress:
        if firmware == entity._target_version or firmware != entity._pre_update_firmware:
            entity._in_progress = False
            entity._cleanup_update()
            _LOGGER.debug("Update complete for %s (now on %s)", entity.device_id, firmware)

    entity.async_write_ha_state()


# ---------------------------------------------------------------------------
# Entity
# ---------------------------------------------------------------------------

class TasmotaUpdateEntity(UpdateEntity):
    """Representation of a Tasmota firmware update."""

    _attr_device_class = "firmware"
    _attr_supported_features = UpdateEntityFeature.INSTALL
    _attr_entity_category = EntityCategory.CONFIG
    _attr_has_entity_name = True

    def __init__(
        self,
        hass: HomeAssistant,
        device_id: str,
        device_name: str,
        firmware_version: str,
        device_topic: str,
        full_topic: str,
        latest_version: str | None,
        device_ip: str | None = None,
        github_repo: str = "arendst/Tasmota",
        ota_firmware: str | None = None,
    ) -> None:
        self.hass = hass
        self.device_id = device_id
        self.firmware_version = firmware_version
        self._device_topic = device_topic
        self.full_topic = full_topic
        self._latest_version = latest_version
        self._device_ip = device_ip
        self._github_repo = github_repo
        self._ota_firmware = ota_firmware
        self._in_progress = False
        self._target_version: str | None = None
        self._pre_update_firmware: str | None = None
        self._grace_until: datetime | None = None
        self._monitor_task: asyncio.Task | None = None

        # Entity identity — with has_entity_name=True, HA prepends device name
        self._attr_name = "Firmware"
        self._attr_unique_id = f"tasmota_update_{device_id}"
        self._attr_available = True

    @property
    def device_info(self) -> DeviceInfo:
        """Return device registry info — links to existing Tasmota device."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.device_id)},
            connections={("mac", self.device_id)},
        )

    # -- grace period --------------------------------------------------------

    def _is_in_grace_period(self) -> bool:
        """Check if we're still in the availability grace period."""
        if self._grace_until is None:
            return False
        return datetime.now(timezone.utc) < self._grace_until

    def _start_grace_period(self) -> None:
        """Start the availability grace period."""
        self._grace_until = datetime.now(timezone.utc) + GRACE_PERIOD

    # -- update monitor task -------------------------------------------------

    async def _monitor_update(self) -> None:
        """Monitor update progress and handle timeout/cleanup."""
        try:
            while self._is_in_grace_period():
                await asyncio.sleep(10)
        except asyncio.CancelledError:
            return

        # Grace period expired — clean up
        if self._in_progress:
            _LOGGER.warning(
                "Update grace period expired for %s — clearing in_progress",
                self.device_id,
            )
            self._in_progress = False
            self._target_version = None
            self.async_write_ha_state()

    def _cleanup_update(self) -> None:
        """Clean up update resources."""
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            self._monitor_task = None

    # -- version properties --------------------------------------------------

    @property
    def installed_version(self) -> str | None:
        return self.firmware_version if self.firmware_version != "unknown" else None

    @property
    def latest_version(self) -> str | None:
        return self._latest_version or self.installed_version

    # -- update progress -----------------------------------------------------

    @property
    def in_progress(self) -> bool:
        return self._in_progress

    # -- release metadata ----------------------------------------------------

    @property
    def release_url(self) -> str | None:
        if self._latest_version:
            return f"https://github.com/{self._github_repo}/releases/tag/v{self._latest_version}"
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {
            "in_progress": self._in_progress,
            "ota_firmware": self._ota_firmware,
        }
        if self._device_ip:
            attrs["device_ip"] = self._device_ip
        return attrs

    @property
    def entity_picture(self) -> str:
        return "https://brands.home-assistant.io/_/tasmota_update/dark_icon.png"

    # -- install action ------------------------------------------------------

    async def async_install(self, version: str | None, backup: bool, **kwargs) -> None:
        """Send MQTT upgrade command to the device."""
        target = version or self._latest_version
        if not target:
            _LOGGER.error("No target version for %s", self.device_id)
            return

        # Clean up any prior update attempt
        self._cleanup_update()

        self._in_progress = True
        self._target_version = target
        self._pre_update_firmware = self.firmware_version
        self._start_grace_period()
        self.async_write_ha_state()

        mqtt_topic = (
            self.full_topic
            .replace("%prefix%", "cmnd")
            .replace("%topic%", self._device_topic)
            + "upgrade"
        )
        _LOGGER.info("Sending upgrade command to %s (topic: %s)", self.device_id, mqtt_topic)

        try:
            await async_publish(self.hass, mqtt_topic, "1")
        except Exception:  # noqa: BLE001
            _LOGGER.error("Failed to publish upgrade command for %s", self.device_id, exc_info=True)
            self._cleanup_update()
            self._in_progress = False
            self._target_version = None
            self.async_write_ha_state()
            return

        # Launch monitor task to handle timeout and cleanup
        self._monitor_task = self.hass.async_create_task(self._monitor_update())

    # -- called from __init__.py when new version is fetched -----------------

    def set_latest_version(self, version: str) -> None:
        """Update the latest available version and push state."""
        self._latest_version = version
        self.async_write_ha_state()
