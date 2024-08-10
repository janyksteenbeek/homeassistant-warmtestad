from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback

from .const import (
    CONF_ASSET_ID,
    CONF_CHANNEL_ID,
    CONF_CONNECTION_ID,
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_PORTFOLIO_ID,
    DOMAIN,
)


@callback
def configured_instances(hass):
    return {entry.title for entry in hass.config_entries.async_entries(DOMAIN)}


class WarmtestadConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            # Ensure the same configuration isn't added twice
            if user_input[CONF_EMAIL] in configured_instances(self.hass):
                errors["base"] = "already_configured"
            else:
                return self.async_create_entry(
                    title=user_input[CONF_EMAIL], data=user_input
                )

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_EMAIL,
                    description={
                        "name": "Email (e.g., your.email@gmail.com)",
                    },
                ): str,
                vol.Required(
                    CONF_PASSWORD,
                    description={
                        "name": "Password (Your Warmtestad password)",
                    },
                ): str,
                vol.Required(
                    CONF_PORTFOLIO_ID,
                    description={
                        "suggested_value": "",
                        "name": "Portfolio ID (e.g., 1234567890)",
                    },
                ): str,
                vol.Required(
                    CONF_CONNECTION_ID,
                    description={
                        "suggested_value": "",
                        "name": "Connection ID (e.g., 9876543210)",
                    },
                ): str,
                vol.Required(
                    CONF_ASSET_ID,
                    description={
                        "suggested_value": "",
                        "name": "Asset ID (e.g., 1122334455)",
                    },
                ): str,
                vol.Required(
                    CONF_CHANNEL_ID,
                    description={
                        "suggested_value": "",
                        "name": "Channel ID (e.g., 9988776655)",
                    },
                ): str,
            }
        )

        return self.async_show_form(
            step_id="user", data_schema=data_schema, errors=errors
        )
