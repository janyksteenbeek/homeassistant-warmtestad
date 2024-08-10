from datetime import timedelta
import logging

import aiohttp

import homeassistant
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity
from homeassistant.util import Throttle

from .const import (
    CONF_ASSET_ID,
    CONF_CHANNEL_ID,
    CONF_CONNECTION_ID,
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_PORTFOLIO_ID,
)

_LOGGER = logging.getLogger(__name__)

MIN_TIME_BETWEEN_UPDATES = timedelta(days=1)

WARMTESTAD_BASE_URL = "https://portalwarmtestad-prd.azurewebsites.net"


class WarmtestadSensor(Entity):
    def __init__(self, hass: HomeAssistant, config) -> None:
        self.hass = hass
        self._email = config[CONF_EMAIL]
        self._password = config[CONF_PASSWORD]
        self._portfolio_id = config[CONF_PORTFOLIO_ID]
        self._connection_id = config[CONF_CONNECTION_ID]
        self._asset_id = config[CONF_ASSET_ID]
        self._channel_id = config[CONF_CHANNEL_ID]
        self._state = None
        self._token = None
        self._user_id = None
        self._session = homeassistant.helpers.aiohttp_client.async_get_clientsession(
            self.hass
        )
        hass.async_create_task(self.update())

    async def authenticate(self) -> None:
        _LOGGER.debug("[Warmtestad] Authenticating with %s", self._email)
        async with self._session.post(
            f"{WARMTESTAD_BASE_URL}/auth/login",
            json={
                "email": self._email,
                "password": self._password,
                "grantType": "password",
            },
        ) as response:
            if response.status == 201:
                data = await response.json(content_type=None)
                self._token = data["accessToken"]
                self._user_id = response.headers.get("Location").split("/")[-1]
            else:
                _LOGGER.error("Authentication failed: %s", response.status)

    async def fetch_data(self) -> None:
        if not self._token:
            await self.authenticate()

        if self._token:
            url = f"{WARMTESTAD_BASE_URL}/users/{self._user_id}/portfolios/{self._portfolio_id}/connections/{self._connection_id}/assets/{self._asset_id}/channels/{self._channel_id}/indexes?page=1"
            headers = {"Authorization": f"Bearer {self._token}"}
            _LOGGER.debug("[Warmtestad] Fetching data from %s", url)
            async with self._session.get(url, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("data"):
                        self._state = data["data"][0]["value"]
                else:
                    _LOGGER.error("Failed to fetch data: %s", response.status)

    @Throttle(MIN_TIME_BETWEEN_UPDATES)
    async def update(self) -> None:
        await self.fetch_data()

    @property
    def name(self) -> str:
        return f"Warmtestad Heat Usage - {self._email}"

    @property
    def state(self) -> str:
        return self._state

    @property
    def unit_of_measurement(self) -> str:
        return "GJ"

    @property
    def icon(self) -> str:
        return "mdi:fire"

    async def async_will_remove_from_hass(self) -> None:
        await self._session.close()


async def async_setup_platform(
    hass, config, async_add_entities, discovery_info=None
) -> None:
    _LOGGER.debug("Setting up Warmtestad sensor from YAML config")
    sensors = [WarmtestadSensor(hass, config)]
    async_add_entities(sensors, True)


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    _LOGGER.debug("Setting up Warmtestad sensor from UI config entry")
    sensor = WarmtestadSensor(hass, entry.data)
    async_add_entities([sensor], True)
