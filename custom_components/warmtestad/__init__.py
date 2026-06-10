"""Warmtestad integration for Home Assistant."""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import CONF_EMAIL, CONF_PASSWORD, DOMAIN

PLATFORMS: list[Platform] = [Platform.SENSOR]
_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = entry.data
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate v1 entries (which stored manual portfolio/connection/asset/channel
    IDs for the old REST API) to v2, which only needs email + password."""
    if entry.version == 1:
        data = {
            CONF_EMAIL: entry.data.get(CONF_EMAIL),
            CONF_PASSWORD: entry.data.get(CONF_PASSWORD),
        }
        hass.config_entries.async_update_entry(
            entry, data=data, unique_id=str(data[CONF_EMAIL]).lower(), version=2
        )
        _LOGGER.info("Migrated Warmtestad config entry to version 2")
    return True
