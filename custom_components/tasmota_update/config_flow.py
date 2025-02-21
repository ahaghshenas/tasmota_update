from homeassistant import config_entries
from homeassistant.core import callback

class TasmotaUpdateConfigFlow(config_entries.ConfigFlow, domain="tasmota_update"):
    """Handle a config flow for Tasmota Update."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is None:
            return self.async_show_form(step_id="user")

        return self.async_create_entry(title="Tasmota Update", data={})