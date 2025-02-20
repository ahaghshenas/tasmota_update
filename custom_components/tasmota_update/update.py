import logging
import aiohttp
import json
from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.components.mqtt import async_publish, async_subscribe

_LOGGER = logging.getLogger(__name__)

DOMAIN = "tasmota_update"

# Track discovered devices to avoid duplicates
_discovered_devices = set()

async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
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
            entity = TasmotaUpdateEntity(hass, device_id, device_name, firmware_version, device_topic, full_topic)
            async_add_entities([entity])

            # Store the entity in hass.data for later updates
            if DOMAIN not in hass.data:
                hass.data[DOMAIN] = {}
            if "entities" not in hass.data[DOMAIN]:
                hass.data[DOMAIN]["entities"] = []
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

    def __init__(self, hass, device_id, device_name, firmware_version, device_topic, full_topic):
        """Initialize the entity."""
        self.hass = hass  # Store the hass object
        self._device_id = device_id
        self._device_name = device_name
        self._firmware_version = firmware_version
        self._device_topic = device_topic  # Store the device topic (extracted from "t")
        self._full_topic = full_topic  # Store the full topic (extracted from "ft")
        self._latest_version = None  # Internal attribute to store the latest version
        self._attr_name = f"Tasmota {device_name} Update"
        self._attr_unique_id = f"tasmota_update_{device_id}"
        self._in_process = False  # Track if an update is in progress
        self._target_version = None  # Track the target firmware version

        # Enable the "Install" button by setting supported features
        self._attr_supported_features = UpdateEntityFeature.INSTALL

        # Debug log for entity initialization
        _LOGGER.debug(f"Initializing entity: Name={self._attr_name}, Unique ID={self._attr_unique_id}")

        # Fetch the latest version on initialization
        self.hass.async_create_task(self.async_update_latest_version())

    async def async_added_to_hass(self):
        """Run when entity is added to Home Assistant."""
        await super().async_added_to_hass()

        # Explicitly set the entity ID
        desired_entity_id = f"update.tasmota_{self._device_name.lower().replace(' ', '_')}_update"
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
        # Use the latest version as the target version if no version is provided
        target_version = version if version else self._latest_version
        _LOGGER.info(f"Updating Tasmota device {self._device_name} to version {target_version}")

        # Set the in_process flag to True to indicate an update is in progress
        self._in_process = True
        self._target_version = target_version  # Set the target firmware version
        _LOGGER.debug(f"Setting in_progress to True for {self._device_name} (target version: {target_version})")
        self.schedule_update_ha_state()  # Notify HA of state change

        # Construct the MQTT topic for the upgrade command
        # Replace %prefix% with "cmnd" and %topic% with the device topic
        mqtt_topic = self._full_topic.replace("%prefix%", "cmnd").replace("%topic%", self._device_topic) + "upgrade"
        _LOGGER.debug(f"Sending MQTT command to topic: {mqtt_topic}")

        try:
            # Send the MQTT command to trigger the firmware update
            await async_publish(self.hass, mqtt_topic, "1")  # Use async_publish directly
            _LOGGER.info(f"Successfully sent MQTT command to update {self._device_name} to {target_version}")
        except Exception as e:
            _LOGGER.error(f"Failed to send MQTT command for update: {e}")
            self._in_process = False  # Reset the in_process flag if the update fails
            self._target_version = None  # Clear the target version
            _LOGGER.debug(f"Setting in_progress to False for {self._device_name} due to error")
            self.schedule_update_ha_state()  # Notify HA of state change

    async def async_update_latest_version(self):
        """Fetch the latest firmware version and update the internal attribute."""
        self._latest_version = await self.async_get_latest_version()
        if self._latest_version:
            _LOGGER.debug(f"Successfully fetched latest version: {self._latest_version}")
        else:
            _LOGGER.debug("Failed to fetch latest version, falling back to installed version")
        if self.hass:
            self.schedule_update_ha_state()  # Notify HA of state change

    @property
    def installed_version(self):
        """Return the currently installed firmware version."""
        # Prepend 'v' to the firmware version
        if self._firmware_version:
            return f"v{self._firmware_version}"
        return None

    @property
    def latest_version(self):
        """Return the latest available firmware version."""
        if self._latest_version:
            return self._latest_version
        return self.installed_version

    async def async_get_latest_version(self):
        """Fetch the latest firmware version from an external source."""
        url = "https://api.github.com/repos/arendst/Tasmota/releases/latest"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        latest_version = data.get("tag_name")
                        _LOGGER.debug(f"Fetched latest version from GitHub: {latest_version}")
                        return latest_version
                    else:
                        _LOGGER.error(f"Failed to fetch latest version: HTTP {response.status}")
        except Exception as e:
            _LOGGER.error(f"Error fetching latest version: {e}")
        return None  # Return None if fetching fails

    async def async_will_remove_from_hass(self):
        """Clean up when the entity is removed."""
        if DOMAIN in self.hass.data and "entities" in self.hass.data[DOMAIN]:
            self.hass.data[DOMAIN]["entities"].remove(self)