from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries

from .blazor_client import WarmtestadAuthError, WarmtestadBlazorClient, WarmtestadError
from .const import CONF_EMAIL, CONF_PASSWORD, DOMAIN


class WarmtestadConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 2
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_EMAIL].lower())
            self._abort_if_unique_id_configured()

            try:
                async with WarmtestadBlazorClient(
                    user_input[CONF_EMAIL], user_input[CONF_PASSWORD]
                ) as client:
                    await client.login()
            except WarmtestadAuthError:
                errors["base"] = "invalid_auth"
            except WarmtestadError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=user_input[CONF_EMAIL], data=user_input
                )

        data_schema = vol.Schema(
            {
                vol.Required(CONF_EMAIL): str,
                vol.Required(CONF_PASSWORD): str,
            }
        )
        return self.async_show_form(
            step_id="user", data_schema=data_schema, errors=errors
        )
