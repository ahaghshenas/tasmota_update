"""Config flow for Tasmota Update integration."""
from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback

DOMAIN = "tasmota_update"

DEFAULT_CLEANUP_DAYS = 7
DEFAULT_GITHUB_REPO = "arendst/Tasmota"

STEP_USER_DATA_SCHEMA = vol.Schema({})

STEP_INIT_DATA_SCHEMA = vol.Schema(
    {
        vol.Optional(
            "cleanup_days",
            default=DEFAULT_CLEANUP_DAYS,
        ): vol.All(int, vol.Range(min=1, max=365)),
        vol.Optional(
            "github_repo",
            default=DEFAULT_GITHUB_REPO,
        ): str,
    }
)


class TasmotaUpdateConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Tasmota Update."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is None:
            return self.async_show_form(step_id="user")

        return self.async_create_entry(
            title="Tasmota Update",
            data={},
            options={
                "cleanup_days": DEFAULT_CLEANUP_DAYS,
                "github_repo": DEFAULT_GITHUB_REPO,
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> TasmotaUpdateOptionsFlow:
        """Get the options flow for this handler."""
        return TasmotaUpdateOptionsFlow(config_entry)


class TasmotaUpdateOptionsFlow(config_entries.OptionsFlowWithConfigEntry):
    """Handle options flow for Tasmota Update."""

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        "cleanup_days",
                        default=current.get("cleanup_days", DEFAULT_CLEANUP_DAYS),
                    ): vol.All(int, vol.Range(min=1, max=365)),
                    vol.Optional(
                        "github_repo",
                        default=current.get("github_repo", DEFAULT_GITHUB_REPO),
                    ): str,
                }
            ),
        )
