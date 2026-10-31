"""Account polling and serialized, cloud-confirmed key commands."""
import asyncio
from functools import partial
from typing import Any
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_DEVICE_IDS, DEFAULT_SCAN_INTERVAL, DOMAIN
from .protocol import KEYS, MiboError, Switches, key_definition
from .runtime import AccountRuntime, RuntimeClosed

_LOGGER = logging.getLogger(__name__)
type Snapshots = dict[str, dict[str, dict[str, Any] | None]]


class MiboCoordinator(DataUpdateCoordinator[Snapshots]):
    """Refresh one discovery snapshot and isolate device-specific failures."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry,
                 runtime: AccountRuntime, device_ids: list[str]) -> None:
        super().__init__(hass, _LOGGER, config_entry=entry, name=DOMAIN,
                         update_interval=DEFAULT_SCAN_INTERVAL)
        self.runtime = runtime
        self.device_ids = tuple(device_ids)
        self.devices: dict[str, dict[str, Any]] = {}
        self.stopping = False
        self._switches = Switches(runtime.client)
        # Keep executor-result delivery ordered with command publications.
        self._operation_lock = asyncio.Lock()

    def _refresh(self) -> tuple[dict, Snapshots]:
        devices = self._switches.discover()
        snapshots = {}
        for device_id in dict.fromkeys((*self.device_ids, *devices)):
            try:
                snapshots[device_id] = self._switches.status(device_id, devices)
            except MiboError as error:
                if error.invalidate_session:
                    raise
                snapshots[device_id] = {ref: None for _, ref in KEYS.values()}
        return devices, snapshots

    async def _async_update_data(self) -> Snapshots:
        async with self._operation_lock:
            try:
                if self.stopping:
                    raise RuntimeClosed
                devices, snapshots = await self.runtime.runner.async_run(self._refresh)
                if self.stopping:
                    raise RuntimeClosed
            except MiboError as error:
                if error.invalidate_session:
                    raise ConfigEntryAuthFailed('The cloud session must be renewed.') from None
                raise UpdateFailed('Unable to refresh the cloud device list.') from None
            except RuntimeClosed:
                raise UpdateFailed('The integration is unloading.') from None
            self.devices.update(devices)
            self.device_ids = tuple(snapshots)
            if list(self.device_ids) != self.config_entry.options.get(CONF_DEVICE_IDS):
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    options={**self.config_entry.options, CONF_DEVICE_IDS: list(self.device_ids)})
            return snapshots

    async def async_set(self, device_id: str, desired: bool, *, key: int = 1) -> None:
        """Await one whole command transaction without optimistic state or replay."""
        if self.stopping or self.runtime.runner.closed:
            raise HomeAssistantError('The integration is unloading.')
        async with self._operation_lock:
            _, ref = key_definition(key)
            if self.stopping or self.runtime.runner.closed:
                raise HomeAssistantError('The integration is unloading.')
            try:
                result = await self.runtime.runner.async_run(
                    partial(self._switches.set, device_id, desired, key=key))
            except RuntimeClosed:
                raise HomeAssistantError('The integration is unloading.') from None
            except MiboError as error:
                if not self.stopping:
                    if error.invalidate_session:
                        self.async_set_update_error(
                            ConfigEntryAuthFailed('The cloud session must be renewed.'))
                        self.config_entry.async_start_reauth_if_available(self.hass)
                    else:
                        self.async_set_updated_data({**self.data, device_id: {
                            **self.data[device_id], ref: None}})
                raise HomeAssistantError('The switch command could not be confirmed.') from None
            if self.stopping:
                raise HomeAssistantError('The integration is unloading.')
            self.async_set_updated_data({**self.data, device_id: {
                **self.data[device_id], ref: result}})
