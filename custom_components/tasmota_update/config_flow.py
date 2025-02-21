import logging
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

_LOGGER = logging.getLogger(__name__)

DOMAIN = "tasmota_update"

class TasmotaUpdateConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Tasmota Update."""

    VERSION = 1

    async def async_step_user(self, user_input=None) -> FlowResult:
        """Handle the initial step."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is None:
            return self.async_show_form(step_id="user")

        return self.async_create_entry(title="Tasmota Update", data={})

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return TasmotaUpdateOptionsFlowHandler(config_entry)


class TasmotaUpdateOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle Tasmota Update options."""

    def __init__(self, config_entry):
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            # Handle user input here
            return self.async_create_entry(data=user_input)

        return self.async_show_form(step_id="init")