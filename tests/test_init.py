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


async def test_selected_keys_and_account_scoped_registries(hass, entry, cloud):
    hass.config_entries.async_update_entry(entry, options={'device_ids': ['switch-a']})
    registry = er.async_get(hass)
    identity = f'{account_namespace(entry.data["email"])}:switch-a'
    existing_device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, identity)})
    existing = registry.async_get_or_create(
        'switch', DOMAIN, f'{identity}:11900', config_entry=entry,
        device_id=existing_device.id, suggested_object_id='saved_key')
    existing = registry.async_update_entity(existing.entity_id, name='Custom key name')
    saved_data = dict(entry.data)
    saved_options = {'device_ids': ['switch-a', 'switch-b']}
    await setup(hass, entry)
    records = er.async_entries_for_config_entry(registry, entry.entry_id)
    assert len(records) == 6
    record = next(r for r in records if r.unique_id == f'{identity}:11900')
    assert record.unique_id == f'{account_namespace(entry.data["email"])}:switch-a:11900'
    assert (record.entity_id, record.unique_id, record.device_id, record.name) == (
        existing.entity_id, existing.unique_id, existing.device_id, 'Custom key name')
    assert entry.data == saved_data
    assert entry.options == saved_options
    assert {r.original_name for r in records} == {'Key 1', 'Key 2', 'Key 3'}
    assert existing_device.id in {r.device_id for r in records}
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
    before = {r.unique_id: (r.entity_id, r.device_id, r.name) for r in records}
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    after = {r.unique_id: (r.entity_id, r.device_id, r.name)
             for r in er.async_entries_for_config_entry(registry, entry.entry_id)}
    assert after == before
    assert entry.data == saved_data
    assert entry.options == saved_options


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
    command = asyncio.create_task(coordinator.async_set('switch-a', True, key=2))
    assert await asyncio.to_thread(cloud.write_started.wait, 5)
    queued = asyncio.create_task(coordinator.async_set('switch-a', True, key=3))
    await asyncio.sleep(0)
    assert len(cloud.writes) == 1
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
    with pytest.raises(HomeAssistantError, match='unloading'):
        await queued
    assert all(state.state == 'unavailable' for state in hass.states.async_all('switch'))
    assert coordinator.data['switch-a']['127000']['api_state'] is False
    assert len(cloud.writes) == 1
    assert cloud.writes[0]['properties'] == {'127000': 1}
    await setup(hass, entry)
    assert entry.runtime_data is not runtime
    assert len(hass.states.async_all('switch')) == 6
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
    assert result['type'] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    entry = result['result']
    assert entry.state is ConfigEntryState.LOADED
    registry = er.async_get(hass)
    before = {r.unique_id: (r.entity_id, r.device_id)
              for r in er.async_entries_for_config_entry(registry, entry.entry_id)}
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
    assert entry.options['device_ids'] == ['switch-a', 'switch-b']
    after = {r.unique_id: (r.entity_id, r.device_id)
             for r in er.async_entries_for_config_entry(registry, entry.entry_id)}
    assert len(after) == 6
    assert after == before
    assert 'password' not in repr(entry.data)
