"""Native switches for the three keys of each selected EIW 1003."""
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import MiboConfigEntry
from .const import DOMAIN
from .coordinator import MiboCoordinator
from .protocol import KEYS, key_definition


async def async_setup_entry(hass: HomeAssistant, entry: MiboConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    """Add selected identities even when an individual read is unavailable."""
    async_add_entities(MiboSwitch(entry.runtime_data.coordinator, device_id, key)
                       for device_id in entry.runtime_data.coordinator.device_ids
                       for key in KEYS)


class MiboSwitch(CoordinatorEntity[MiboCoordinator], SwitchEntity):
    """Expose only cloud-confirmed state for one key."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: MiboCoordinator, device_id: str, key: int) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._key = key
        _, self._ref = key_definition(key)
        self._attr_name = f'Key {key}'
        self._identity = f'{coordinator.runtime.account_namespace}:{device_id}'
        self._attr_unique_id = f'{self._identity}:{self._ref}'

    @property
    def device_info(self) -> DeviceInfo:
        device = self.coordinator.devices.get(self._device_id, {})
        return DeviceInfo(identifiers={(DOMAIN, self._identity)}, manufacturer='Intelbras',
                          model=device.get('model', 'EIW1003'),
                          name=device.get('deviceName', 'EIW 1003'))

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data.get(self._device_id, {}).get(self._ref) is not None

    @property
    def is_on(self) -> bool | None:
        snapshot = self.coordinator.data.get(self._device_id, {}).get(self._ref)
        return snapshot['api_state'] if snapshot else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set(self._device_id, True, key=self._key)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set(self._device_id, False, key=self._key)
