"""Warmtestad heat-consumption sensor backed by the Blazor portal client."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

from .blazor_client import (
    WarmtestadAuthError,
    WarmtestadBlazorClient,
    WarmtestadError,
)
from .const import CONF_EMAIL, CONF_PASSWORD, DOMAIN

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(hours=12)


class WarmtestadCoordinator(DataUpdateCoordinator[float]):
    """Polls the portal once or twice a day for the cumulative consumption."""

    def __init__(self, hass: HomeAssistant, email: str, password: str) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="Warmtestad",
            update_interval=SCAN_INTERVAL,
        )
        self._email = email
        self._password = password

    async def _async_update_data(self) -> float:
        # Use the client's own cookie jar (a fresh authenticated session each
        # poll) rather than Home Assistant's shared session.
        try:
            async with WarmtestadBlazorClient(self._email, self._password) as client:
                value = await client.async_get_consumption_gj()
        except WarmtestadAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except WarmtestadError as err:
            raise UpdateFailed(str(err)) from err
        if value is None:
            raise UpdateFailed("No consumption value found on the portal")
        return value


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> None:
    coordinator = WarmtestadCoordinator(
        hass, entry.data[CONF_EMAIL], entry.data[CONF_PASSWORD]
    )
    await coordinator.async_config_entry_first_refresh()
    async_add_entities([WarmtestadSensor(coordinator, entry)])


class WarmtestadSensor(CoordinatorEntity[WarmtestadCoordinator], SensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Heat usage"
    _attr_native_unit_of_measurement = "GJ"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:fire"

    def __init__(self, coordinator: WarmtestadCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_heat_usage"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Warmtestad",
            manufacturer="Warmtestad",
        )

    @property
    def native_value(self) -> float | None:
        return self.coordinator.data
