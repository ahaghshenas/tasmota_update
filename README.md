# Tasmota Update Integration for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

This is a custom Home Assistant integration that monitors firmware updates for Tasmota devices. It integrates with the [Tasmota MQTT Discovery](https://tasmota.github.io/docs/MQTT-Discovery/) feature to automatically detect Tasmota devices and provide update entities for managing firmware upgrades.

## Features
- **Automatic Discovery**: Automatically discovers Tasmota devices via MQTT Discovery.
- **Firmware Update Management**: Provides update entities to monitor and install the latest firmware versions.
- **Device Tracking**: Links update entities to existing Tasmota devices in Home Assistant's device registry.
- **Full Topic Recording**: Records the full MQTT topic for each device to ensure firmware updates are sent to the correct topic.
- **GitHub Integration**: Fetches the latest firmware version from the official [Tasmota GitHub repository](https://github.com/arendst/Tasmota).
- **HACS Support**: Easily install and manage this integration using [HACS (Home Assistant Community Store)](https://hacs.xyz).

## Installation

### Option 1: Install via HACS (Recommended)
1. Open **HACS** in your Home Assistant instance.
2. Go to **Settings > Custom Repositories**.
3. Add the following repository URL:
   ```
   https://github.com/ahaghshenas/tasmota_update
   ```
Select the category as **Integration**.
5. Search for "Tasmota Update" in HACS and click **Install**.
6. Restart Home Assistant.

### Option 2: Manual Installation
1. Clone or download this repository:
   ```bash
   git clone https://github.com/ahaghshenas/tasmota_update.git
   ```
2. Copy the tasmota_update folder into your Home Assistant custom_components directory:
   ```
   <config_directory>/custom_components/tasmota_update/
   ```
   If the custom_components folder does not exist, create it.
3. Restart Home Assistant.
## Configuration
### Prerequisites
- **MQTT Broker** : Ensure you have an MQTT broker configured in Home Assistant (e.g., Mosquitto).
- **Tasmota Devices** : Your Tasmota devices must be configured to use MQTT Discovery.
### Automatic Setup
This integration uses MQTT Discovery, so no additional configuration is required. Once installed and restarted, Home Assistant will automatically discover Tasmota devices and create update entities for them
### Example Entity Attributes
Each discovered Tasmota device will have an update entity with the following attributes:
- **Installed Version** : The currently installed firmware version (e.g., v14.5.0).
- **Latest Version** : The latest available firmware version fetched from GitHub.
- **In Progress** : Indicates whether a firmware update is in progress.
- **Release URL** : A link to the GitHub release page for the latest firmware version.
## Usage
### Monitoring Firmware Updates
- The integration creates an update entity for each Tasmota device (e.g., update.usb_switch_1_firmware).
- If a firmware update is available, the entity's state will change to on.
- You can view details about the update in the entity's attributes.
### Installing Firmware Updates  
- Use the Install Update button in the Home Assistant UI to trigger a firmware update.
- Alternatively, you can call the update.install service:
  ```yaml
  service: update.install
  target:
    entity_id: update.usb_switch_1_firmware
  ```
### Automations
You can create automations to notify you when updates are available or to automatically install updates. For example:
```yaml
automation:
  - alias: Notify on Tasmota Firmware Update
    trigger:
      platform: state
      entity_id: update.usb_switch_1_firmware
      to: "on"
    action:
      service: notify.notify
      data:
        message: "A firmware update is available for USB Switch 1!"
```
## Troubleshooting
### Debug Logging
To enable debug logging for this integration, add the following to your configuration.yaml:
```yaml
logger:
  default: info
  logs:
    custom_components.tasmota_update: debug
```
Restart Home Assistant and check the logs for detailed information.
### Common Issues
- **Entities Not Discovered** : Ensure that MQTT Discovery is enabled on your Tasmota devices and that the MQTT broker is properly configured in Home Assistant.
- **Update Fails** : Verify that your Tasmota devices are online and reachable via MQTT.
## Contributing
Contributions are welcome! If you encounter any issues or have suggestions for improvement, please open an issue or submit a pull request on GitHub.
## License
This project is licensed under the MIT License. See the LICENSE file for details.
