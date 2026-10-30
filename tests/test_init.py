"""Native config-entry setup, options reload, and account registry isolation."""
import asyncio
import threading
from datetime import timedelta

import pytest

from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.intelbras_mibo.const import DOMAIN
from custom_components.intelbras_mibo.runtime import account_namespace


async def setup(hass, entry):
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_selected_first_keys_and_account_scoped_registries(hass, entry, cloud):
    hass.config_entries.async_update_entry(entry, options={'device_ids': ['switch-a']})
    await setup(hass, entry)
    registry = er.async_get(hass)
    records = er.async_entries_for_config_entry(registry, entry.entry_id)
    assert len(records) == 1
    record = records[0]
    assert record.unique_id == f'{account_namespace(entry.data["email"])}:switch-a:11900'
    assert hass.states.get(record.entity_id).state == 'off'
    device = dr.async_get(hass).async_get(record.device_id)
    assert device.identifiers == {(DOMAIN, f'{account_namespace(entry.data["email"])}:switch-a')}
    assert not cloud.writes
    assert all(thread_id != threading.get_ident() for _, _, thread_id in cloud.calls)
    assert entry.runtime_data.coordinator.update_interval == timedelta(seconds=30)

    other_email = 'other@example.test'
    other = MockConfigEntry(domain=DOMAIN, unique_id=other_email,
                            data=dict(entry.data, email=other_email, account=other_email,
                                      account_namespace=account_namespace(other_email)), options=entry.options)
    other.add_to_hass(hass)
    await setup(hass, other)
    other_record = er.async_entries_for_config_entry(registry, other.entry_id)[0]
    assert other_record.unique_id != record.unique_id
    assert other_record.device_id != record.device_id


async def test_options_reload_removes_only_deselected_entry_records(hass, entry, cloud):
    await setup(hass, entry)
    registry = er.async_get(hass)
    other_email = 'other@example.test'
    other = MockConfigEntry(domain=DOMAIN, unique_id=other_email,
                            data=dict(entry.data, email=other_email, account=other_email,
                                      account_namespace=account_namespace(other_email)),
                            options={'device_ids': ['switch-a']})
    other.add_to_hass(hass)
    await setup(hass, other)
    other_records = er.async_entries_for_config_entry(registry, other.entry_id)
    before = {r.unique_id: r for r in er.async_entries_for_config_entry(registry, entry.entry_id)}
    kept = next(r for r in before.values() if 'switch-b' in r.unique_id)
    cloud.devices['switch-b']['deviceName'] = 'Renamed test switch'
    cloud.devices = dict(reversed(list(cloud.devices.items())))
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result['flow_id'], {'device_ids': ['switch-b']})
    await hass.async_block_till_done()
    records = er.async_entries_for_config_entry(registry, entry.entry_id)
    assert [r.entity_id for r in records] == [kept.entity_id]
    assert len(hass.states.async_all('switch')) == 2
    assert er.async_entries_for_config_entry(registry, other.entry_id) == other_records
    assert len(dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)) == 1
    assert entry.runtime_data.coordinator.data['switch-b']['name'] == 'Renamed test switch'


async def test_setup_shared_failure_and_auth_failure(hass, entry, cloud):
    cloud.list_code = '50000'
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY
    cloud.list_code = '12112'
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert len(flows) == 1
    assert flows[0]['context']['entry_id'] == entry.entry_id


async def test_unload_drains_cancelled_command_and_rejects_late_publication(hass, entry, cloud):
    await setup(hass, entry)
    coordinator = entry.runtime_data.coordinator
    runtime = entry.runtime_data
    cloud.write_started, cloud.write_release = threading.Event(), threading.Event()
    command = asyncio.create_task(coordinator.async_set('switch-a', True))
    assert await asyncio.to_thread(cloud.write_started.wait, 5)
    command.cancel()
    try:
        await command
    except asyncio.CancelledError:
        pass
    unload = asyncio.create_task(hass.config_entries.async_unload(entry.entry_id))
    try:
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(asyncio.shield(unload), 0.1)
        assert runtime.runner.closed
        with pytest.raises(HomeAssistantError, match="unloading"):
            await coordinator.async_set("switch-b", False)
    finally:
        cloud.write_release.set()
    assert await unload
    assert all(state.state == 'unavailable' for state in hass.states.async_all('switch'))
    assert coordinator.data['switch-a']['api_state'] is False
    assert len(cloud.writes) == 1
    await setup(hass, entry)
    assert entry.runtime_data is not runtime
    assert len(hass.states.async_all('switch')) == 2
    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.common import async_fire_time_changed
    cloud.calls.clear()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=31))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert sum(api == 'device.list.BasicList' for api, _, _ in cloud.calls) == 1


async def test_native_user_setup_and_same_account_reauth_keep_entity_ids(hass, cloud):
    from homeassistant.config_entries import SOURCE_USER, SOURCE_REAUTH
    from homeassistant.data_entry_flow import FlowResultType

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={'source': SOURCE_USER},
        data={'email': 'new@example.test', 'password': 'test-password'})
    assert result['step_id'] == 'devices'
    result = await hass.config_entries.flow.async_configure(
        result['flow_id'], {'device_ids': ['switch-a']})
    assert result['type'] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    entry = result['result']
    assert entry.state is ConfigEntryState.LOADED
    registry = er.async_get(hass)
    before = er.async_entries_for_config_entry(registry, entry.entry_id)[0]
    old_runtime = entry.runtime_data
    namespace = entry.data['account_namespace']
    terminal = entry.data['session']['terminal_id']
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={'source': SOURCE_REAUTH, 'entry_id': entry.entry_id}, data=entry.data)
    result = await hass.config_entries.flow.async_configure(
        result['flow_id'], {'email': 'NEW@EXAMPLE.TEST', 'password': 'test-password'})
    assert result['reason'] == 'reauth_successful'
    await hass.async_block_till_done()
    assert old_runtime.runner.closed
    assert entry.runtime_data is not old_runtime
    assert entry.data['account_namespace'] == namespace
    assert entry.data['session']['terminal_id'] == terminal
    assert entry.options['device_ids'] == ['switch-a']
    after = er.async_entries_for_config_entry(registry, entry.entry_id)[0]
    assert (after.entity_id, after.unique_id, after.device_id) == (before.entity_id, before.unique_id, before.device_id)
    assert 'password' not in repr(entry.data)
