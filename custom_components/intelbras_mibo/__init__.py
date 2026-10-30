"""Unofficial community integration for Intelbras Mibo."""
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .const import CONF_DEVICE_IDS, DOMAIN, PLATFORMS
from .coordinator import MiboCoordinator
from .protocol import KEYS, MiboError
from .runtime import AccountRuntime, async_create_runtime


@dataclass
class MiboRuntime(AccountRuntime):
    """Account resources and coordinator owned by the loaded entry."""

    coordinator: MiboCoordinator


type MiboConfigEntry = ConfigEntry[MiboRuntime]


async def async_setup_entry(hass: HomeAssistant, entry: MiboConfigEntry) -> bool:
    """Restore the token session, refresh, and forward selected switches."""
    try:
        account = await async_create_runtime(hass, entry.data)
    except MiboError as error:
        if error.invalidate_session:
            raise ConfigEntryAuthFailed('The cloud session must be renewed.') from None
        raise ConfigEntryNotReady('Unable to restore the cloud session.') from None
    coordinator = MiboCoordinator(hass, entry, account, entry.options[CONF_DEVICE_IDS])
    entry.runtime_data = MiboRuntime(account.client, account.runner,
                                    account.account_namespace, coordinator)
    try:
        await coordinator.async_config_entry_first_refresh()
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except BaseException:
        coordinator.stopping = True
        await coordinator.async_shutdown()
        await account.async_close()
        raise
    _remove_deselected_records(hass, entry)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(hass: HomeAssistant, entry: MiboConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


def _remove_deselected_records(hass: HomeAssistant, entry: MiboConfigEntry) -> None:
    namespace = entry.runtime_data.account_namespace
    selected = {f'{namespace}:{device_id}' for device_id in entry.options[CONF_DEVICE_IDS]}
    selected_entities = {f'{identity}:{ref}' for identity in selected
                         for _, ref in KEYS.values()}
    entities = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(entities, entry.entry_id):
        if entity.unique_id not in selected_entities:
            entities.async_remove(entity.entity_id)
    devices = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(devices, entry.entry_id):
        if not any(domain == DOMAIN and identifier in selected
                   for domain, identifier in device.identifiers):
            devices.async_update_device(device.id, remove_config_entry_id=entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: MiboConfigEntry) -> bool:
    """Stop publications and drain account work before allowing replacement."""
    runtime = entry.runtime_data
    runtime.coordinator.stopping = True
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        runtime.coordinator.stopping = False
        await runtime.coordinator.async_request_refresh()
        return False
    await runtime.coordinator.async_shutdown()
    await runtime.async_close()
    return True
