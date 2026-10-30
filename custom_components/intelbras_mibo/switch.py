"""One native switch for the first key of each selected EIW 1003."""
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import MiboConfigEntry
from .const import DOMAIN
from .coordinator import MiboCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: MiboConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    """Add selected identities even when an individual read is unavailable."""
    async_add_entities(MiboSwitch(entry.runtime_data.coordinator, device_id)
                       for device_id in entry.runtime_data.coordinator.device_ids)


class MiboSwitch(CoordinatorEntity[MiboCoordinator], SwitchEntity):
    """Expose only cloud-confirmed state for key 1."""

    _attr_has_entity_name = True
    _attr_name = 'Key 1'

    def __init__(self, coordinator: MiboCoordinator, device_id: str) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._identity = f'{coordinator.runtime.account_namespace}:{device_id}'
        self._attr_unique_id = f'{self._identity}:11900'

    @property
    def device_info(self) -> DeviceInfo:
        device = self.coordinator.devices.get(self._device_id, {})
        return DeviceInfo(identifiers={(DOMAIN, self._identity)}, manufacturer='Intelbras',
                          model=device.get('model', 'EIW1003'),
                          name=device.get('deviceName', 'EIW 1003'))

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data.get(self._device_id) is not None

    @property
    def is_on(self) -> bool | None:
        snapshot = self.coordinator.data.get(self._device_id)
        return snapshot['api_state'] if snapshot else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set(self._device_id, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set(self._device_id, False)
