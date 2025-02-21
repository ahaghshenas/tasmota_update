import logging
import aiohttp
import json
from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.components.mqtt import async_publish, async_subscribe
from homeassistant.helpers.entity import DeviceInfo

_LOGGER = logging.getLogger(__name__)

DOMAIN = "tasmota_update"

# Track discovered devices to avoid duplicates
_discovered_devices = set()


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the Tasmota Update platform using MQTT Discovery."""
    _LOGGER.debug("Setting up Tasmota Update platform with MQTT Discovery")

    async def async_device_message_received(msg):
        """Handle MQTT Discovery messages."""
        topic = msg.topic
        payload = msg.payload

        # Only process messages from the "config" topic
        if not topic.endswith("/config"):
            return

        try:
            # Parse the JSON payload
            payload_dict = json.loads(payload)
            device_id = topic.split("/")[-2]  # Extract device ID from the topic

            # Check if the device has already been processed
            if device_id in _discovered_devices:
                # If the device is already processed, update its firmware version
                for entity in hass.data[DOMAIN]["entities"]:
                    if entity._device_id == device_id:
                        firmware_version = payload_dict.get("sw", "unknown")
                        _LOGGER.debug(f"Updating firmware version for device {device_id} to {firmware_version}")

                        # Only set in_progress to False if the firmware version matches the target version
                        if entity._in_process and firmware_version == entity._target_version.lstrip("v"):
                            entity._in_process = False
                            _LOGGER.debug(f"Setting in_progress to False for device {device_id} (target version reached)")
                            entity.schedule_update_ha_state()  # Notify HA of state change

                        # Update the firmware version
                        entity._firmware_version = firmware_version
                        entity.schedule_update_ha_state()  # Notify HA of state change
                        break
                return

            # Mark the device as processed
            _discovered_devices.add(device_id)

            device_name = payload_dict.get("dn", device_id)  # Use "dn" (device name) or fallback to device_id
            firmware_version = payload_dict.get("sw", "unknown")  # Use "sw" (firmware version) or fallback to "unknown"
            device_topic = payload_dict.get("t", device_id)  # Use "t" (topic) or fallback to device_id
            full_topic = payload_dict.get("ft", f"%prefix%/%topic%/")  # Use "ft" (full topic) or fallback to default

            _LOGGER.debug(f"Discovered Tasmota device: {device_name} (ID: {device_id}), Firmware: {firmware_version}, Topic: {device_topic}, Full Topic: {full_topic}")

            # Create an update entity for the discovered device
            entity = TasmotaUpdateEntity(hass, device_id, device_name, firmware_version, device_topic, full_topic, hass.data[DOMAIN]["latest_version"])
            async_add_entities([entity])

            # Store the entity in hass.data for later updates
            hass.data[DOMAIN]["entities"].append(entity)

        except json.JSONDecodeError:
            _LOGGER.error(f"Failed to parse MQTT payload as JSON: {payload}")
        except Exception as e:
            _LOGGER.error(f"Error processing MQTT message: {e}")

    # Subscribe to the MQTT Discovery topic
    await async_subscribe(hass, "tasmota/discovery/#", async_device_message_received)

    return True


class TasmotaUpdateEntity(UpdateEntity):
    """Representation of a Tasmota Update entity."""

    def __init__(self, hass, device_id, device_name, firmware_version, device_topic, full_topic, latest_version=None):
        """Initialize the entity."""
        self.hass = hass
        self._device_id = device_id
        self._device_name = device_name
        self._firmware_version = firmware_version
        self._device_topic = device_topic
        self._full_topic = full_topic
        self._latest_version = latest_version  # Use the globally fetched version
        self._attr_name = f"{device_name} Firmware"
        self._attr_unique_id = f"tasmota_update_{device_id}"
        self._in_process = False
        self._target_version = None
        self._attr_supported_features = UpdateEntityFeature.INSTALL
        self._attr_device_class = "firmware"

        _LOGGER.debug(f"Initializing entity: Name={self._attr_name}, Unique ID={self._attr_unique_id}")

    @property
    def device_info(self) -> dict:
        """Return information about the device."""
        return {
            "identifiers": {(DOMAIN, self._device_id)},
            "connections": {("mac", self._device_id)}
        }

    @property
    def entity_picture(self):
        """Return the entity picture URL."""
        return "https://brands.home-assistant.io/tasmota/dark_icon.png"

    @property
    def release_url(self):
        """Return the release URL for the latest firmware version."""
        if self._latest_version:
            return f"https://github.com/arendst/Tasmota/releases/tag/{self._latest_version}"
        return None

    @property
    def in_progress(self):
        """Return the update progress status."""
        _LOGGER.debug(f"Getting in_progress status for {self._device_name}: {self._in_process}")
        return self._in_process

    @property
    def state(self):
        """Return the state of the entity."""
        if self.installed_version != self.latest_version:
            return "on"  # Update available
        return "off"  # Up-to-date

    @property
    def extra_state_attributes(self):
        """Return additional state attributes."""
        return {
            "in_progress": self._in_process,
            "installed_version": self.installed_version,
            "latest_version": self.latest_version,
        }

    async def async_install(self, version, backup, **kwargs):
        """Install the latest firmware."""
        target_version = version if version else self._latest_version
        _LOGGER.info(f"Updating Tasmota device {self._device_name} to version {target_version}")

        # Set the in_process flag to True to indicate an update is in progress
        self._in_process = True
        self._target_version = target_version
        _LOGGER.debug(f"Setting in_progress to True for {self._device_name} (target version: {target_version})")
        self.schedule_update_ha_state()

        # Construct the MQTT topic for the upgrade command
        mqtt_topic = self._full_topic.replace("%prefix%", "cmnd").replace("%topic%", self._device_topic) + "upgrade"
        _LOGGER.debug(f"Sending MQTT command to topic: {mqtt_topic}")

        try:
            await async_publish(self.hass, mqtt_topic, "1")
            _LOGGER.info(f"Successfully sent MQTT command to update {self._device_name} to {target_version}")
        except Exception as e:
            _LOGGER.error(f"Failed to send MQTT command for update: {e}")
            self._in_process = False
            self._target_version = None
            _LOGGER.debug(f"Setting in_progress to False for {self._device_name} due to error")
            self.schedule_update_ha_state()

    @property
    def installed_version(self):
        """Return the currently installed firmware version."""
        if self._firmware_version:
            return f"v{self._firmware_version}"
        return None

    @property
    def latest_version(self):
        """Return the latest available firmware version."""
        if self._latest_version:
            return self._latest_version
        return self.installed_version

    async def async_will_remove_from_hass(self):
        """Clean up when the entity is removed."""
        if DOMAIN in self.hass.data and "entities" in self.hass.data[DOMAIN]:
            self.hass.data[DOMAIN]["entities"].remove(self)