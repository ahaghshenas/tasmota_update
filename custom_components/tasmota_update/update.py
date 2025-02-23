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
            for entity in hass.data[DOMAIN]["entities"]:
                if entity._device_id == device_id:
                    # If the device is already processed, check for changes in full_topic
                    new_full_topic = payload_dict.get("ft", f"%prefix%/%topic%/")
                    if entity._full_topic != new_full_topic:
                        _LOGGER.info(f"Detected full_topic change for device {device_id}: {entity._full_topic} -> {new_full_topic}")

                        # Update the full_topic in the entity
                        entity._full_topic = new_full_topic

                        # Re-subscribe to the new LWT topic
                        new_lwt_topic = new_full_topic.replace("%prefix%", "tele").replace("%topic%", entity._device_topic) + "LWT"
                        await async_subscribe(hass, new_lwt_topic, lambda msg: lwt_message_received(entity, msg))
                        entity._lwt_topic = new_lwt_topic  # Update the stored LWT topic

                        _LOGGER.debug(f"Re-subscribed to LWT topic for device {device_id}: {new_lwt_topic}")

                        # Notify HA of state change
                        entity.schedule_update_ha_state()

                    # Update the firmware version
                    firmware_version = payload_dict.get("sw", "unknown")
                    _LOGGER.debug(f"Updating firmware version for device {device_id} to {firmware_version}")
                    entity._firmware_version = firmware_version

                    # Only set in_progress to False if the firmware version matches the target version
                    if entity._in_process and firmware_version == entity._target_version.lstrip("v"):
                        entity._in_process = False
                        _LOGGER.debug(f"Setting in_progress to False for device {device_id} (target version reached)")
                    entity.schedule_update_ha_state()
                    break
            else:
                # Mark the device as processed
                _discovered_devices.add(device_id)

                device_name = payload_dict.get("dn", device_id)  # Use "dn" (device name) or fallback to device_id
                firmware_version = payload_dict.get("sw", "unknown")  # Use "sw" (firmware version) or fallback to "unknown"
                device_topic = payload_dict.get("t", device_id)  # Use "t" (topic) or fallback to device_id
                full_topic = payload_dict.get("ft", f"%prefix%/%topic%/")  # Use "ft" (full topic) or fallback to default

                # Construct the LWT topic dynamically
                lwt_topic = full_topic.replace("%prefix%", "tele").replace("%topic%", device_topic) + "LWT"
                _LOGGER.debug(f"Constructed LWT topic for device {device_id}: {lwt_topic}")

                _LOGGER.debug(f"Discovered Tasmota device: {device_name} (ID: {device_id}), Firmware: {firmware_version}, Topic: {device_topic}, Full Topic: {full_topic}")

                # Create an update entity for the discovered device
                entity = TasmotaUpdateEntity(
                    hass,
                    device_id,
                    device_name,
                    firmware_version,
                    device_topic,
                    full_topic,
                    hass.data[DOMAIN]["latest_version"],  # Pass the global latest version
                )
                async_add_entities([entity])

                # Store the entity in hass.data for later updates
                hass.data[DOMAIN]["entities"].append(entity)

                # Subscribe to the LWT topic
                await async_subscribe(hass, lwt_topic, lambda msg: lwt_message_received(entity, msg))

        except json.JSONDecodeError:
            _LOGGER.error(f"Failed to parse MQTT payload as JSON: {payload}")
        except Exception as e:
            _LOGGER.error(f"Error processing MQTT message: {e}")

    # Handle LWT messages
    def lwt_message_received(entity, msg):
        """Handle LWT messages."""
        lwt_payload = msg.payload
        _LOGGER.debug(f"LWT message received for device {entity._device_id}: {lwt_payload}")

        if lwt_payload == "Online":
            entity._attr_available = True
            _LOGGER.debug(f"Device {entity._device_id} is Online. Setting entity state to Available.")
        elif lwt_payload == "Offline":
            # Only set the entity to unavailable if no update is in progress
            if not entity._in_process:
                entity._attr_available = False
                _LOGGER.debug(f"Device {entity._device_id} is Offline. Setting entity state to Unavailable.")
            else:
                _LOGGER.debug(f"Device {entity._device_id} is Offline, but an update is in progress. Keeping entity available.")
        entity.schedule_update_ha_state()

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
        self._attr_available = True

        _LOGGER.debug(f"Initializing entity: Name={self._attr_name}, Unique ID={self._attr_unique_id}")

    @property
    def device_info(self) -> dict:
        """Return information about the device."""
        return {
            "identifiers": {(DOMAIN, self._device_id)},
            "connections": {("mac", self._device_id)}
        }

    async def async_added_to_hass(self):
        """Run when entity is added to Home Assistant."""
        await super().async_added_to_hass()

        # Generate the new entity ID format
        desired_entity_id = f"update.{self._device_name.lower().replace(' ', '_')}_firmware"
        _LOGGER.debug(f"Setting entity ID to: {desired_entity_id}")
        self.entity_id = desired_entity_id

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
        if not self.available:
            return "unavailable"  # Device is offline
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