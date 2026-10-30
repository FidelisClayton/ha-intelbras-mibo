"""Unofficial community integration for Intelbras Mibo."""
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from .const import CONF_DEVICE_IDS, PLATFORMS
from .coordinator import MiboCoordinator
from .protocol import MiboError
from .runtime import AccountRuntime, async_create_runtime


@dataclass
class MiboRuntime(AccountRuntime):
    """Account resources and coordinator owned by the loaded entry."""

    coordinator: MiboCoordinator


type MiboConfigEntry = ConfigEntry[MiboRuntime]


async def async_setup_entry(hass: HomeAssistant, entry: MiboConfigEntry) -> bool:
    """Restore the token session, refresh, and forward known switches."""
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
    return True


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
