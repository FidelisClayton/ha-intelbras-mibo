"""Cloud polling keeps per-device failures separate from account failures."""
from datetime import timedelta

import pytest

from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from tests.test_init import setup


def entities(hass, entry):
    return {tuple(r.unique_id.split(':')[-2:]): r.entity_id
            for r in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)}


async def test_real_poll_uses_one_discovery_and_model_per_device_and_restores_key(hass, entry, cloud):
    await setup(hass, entry)
    ids = entities(hass, entry)
    cloud.calls.clear()
    cloud.states['switch-a']['11900'] = True
    cloud.read_failures[('switch-b', '127000')] = '50000'
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=31))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get(ids[('switch-a', '11900')]).state == 'on'
    assert hass.states.get(ids[('switch-b', '127000')]).state == 'unavailable'
    assert all(hass.states.get(ids[('switch-b', ref)]).state == 'on'
               for ref in ('11900', '127100'))
    assert sum(api == 'device.list.BasicList' for api, _, _ in cloud.calls) == 1
    assert sum(api == 'iot.manager.QueryModelInfo' for api, _, _ in cloud.calls) == 2
    assert sum(api == 'iot.control.GetIotProperties' for api, _, _ in cloud.calls) == 6
    assert not cloud.writes
    cloud.read_failures.clear()
    await entry.runtime_data.coordinator.async_refresh()
    assert hass.states.get(ids[('switch-b', '127000')]).state == 'on'
    assert entities(hass, entry) == ids


async def test_initial_unreadable_and_missing_devices_still_load(hass, entry, cloud):
    cloud.read_failures[('switch-a', '11900')] = '50000'
    del cloud.devices['switch-b']
    await setup(hass, entry)
    ids = entities(hass, entry)
    assert len(ids) == 6
    assert hass.states.get(ids[('switch-a', '11900')]).state == 'unavailable'
    assert all(hass.states.get(ids[('switch-a', ref)]).state == 'off'
               for ref in ('127000', '127100'))
    assert all(hass.states.get(ids[('switch-b', ref)]).state == 'unavailable'
               for ref in ('11900', '127000', '127100'))


@pytest.mark.parametrize('transport_failure', [False, True])
async def test_shared_failure_and_recovery(hass, entry, cloud, transport_failure):
    await setup(hass, entry)
    ids = entities(hass, entry)
    cloud.list_code = '50000'
    cloud.list_failure = transport_failure
    await entry.runtime_data.coordinator.async_refresh()
    assert all(hass.states.get(entity_id).state == 'unavailable' for entity_id in ids.values())
    cloud.list_code = None
    cloud.list_failure = False
    await entry.runtime_data.coordinator.async_refresh()
    assert hass.states.get(ids[('switch-a', '11900')]).state == 'off'
    assert hass.states.get(ids[('switch-b', '11900')]).state == 'on'


@pytest.mark.parametrize('ref', ['11900', '127000', '127100'])
async def test_auth_invalid_refresh_requests_same_entry_reauth(hass, entry, cloud, ref):
    await setup(hass, entry)
    cloud.read_failures[('switch-a', ref)] = '12112'
    await entry.runtime_data.coordinator.async_refresh()
    assert isinstance(entry.runtime_data.coordinator.last_exception, ConfigEntryAuthFailed)
    await hass.async_block_till_done()
    progress = hass.config_entries.flow.async_progress()
    assert len(progress) == 1
    assert progress[0]['context']['entry_id'] == entry.entry_id


@pytest.mark.parametrize('failure', ['key1_only', 'invalid_key2', 'malformed_model', 'model_failure'])
async def test_schema_failure_isolation_and_refresh_recovery(hass, entry, cloud, failure):
    product = cloud.devices['switch-a']['productId']
    schema = cloud.models[product]
    if failure == 'key1_only':
        cloud.models[product] = {'properties': schema['properties'][:1]}
    elif failure == 'invalid_key2':
        cloud.models[product] = {'properties': [dict(p, accessMode='r')
            if p['identifier'] == 'std_switch2' else p for p in schema['properties']]}
    elif failure == 'malformed_model':
        cloud.models[product] = 'invalid json'
    else:
        cloud.model_failures[product] = '50000'
    await setup(hass, entry)
    ids = entities(hass, entry)
    assert len(ids) == 6
    unavailable = {'127000'} if failure == 'invalid_key2' else (
        {'127000', '127100'} if failure == 'key1_only' else {'11900', '127000', '127100'})
    for ref in ('11900', '127000', '127100'):
        assert hass.states.get(ids[('switch-a', ref)]).state == (
            'unavailable' if ref in unavailable else 'off')
        assert hass.states.get(ids[('switch-b', ref)]).state == 'on'
    reads = [data['properties'][0] for api, data, _ in cloud.calls
             if api == 'iot.control.GetIotProperties' and data['deviceId'] == 'switch-a']
    assert set(reads) == {'11900', '127000', '127100'} - unavailable
    assert not cloud.writes
    for key, ref in [(1, '11900'), (2, '127000'), (3, '127100')]:
        if ref in unavailable:
            with pytest.raises(HomeAssistantError, match='could not be confirmed'):
                await entry.runtime_data.coordinator.async_set('switch-a', True, key=key)
    assert not cloud.writes
    cloud.models[product] = schema
    cloud.model_failures.clear()
    await entry.runtime_data.coordinator.async_refresh()
    assert entities(hass, entry) == ids
    assert all(hass.states.get(ids[('switch-a', ref)]).state == 'off'
               for ref in ('11900', '127000', '127100'))


async def test_duplicate_device_identity_fails_snapshot_and_recovers(hass, entry, cloud):
    await setup(hass, entry)
    ids = entities(hass, entry)
    cloud.devices['duplicate'] = cloud.devices['switch-a']
    cloud.calls.clear()
    await entry.runtime_data.coordinator.async_refresh()
    assert all(hass.states.get(entity).state == 'unavailable' for entity in ids.values())
    assert [api for api, _, _ in cloud.calls] == ['device.list.BasicList']
    del cloud.devices['duplicate']
    await entry.runtime_data.coordinator.async_refresh()
    assert entities(hass, entry) == ids
    assert all(hass.states.get(entity).state in ('on', 'off') for entity in ids.values())


@pytest.mark.parametrize('failure', ['removed', 'unsupported', 'schema', 'model_failure'])
async def test_refresh_invalidates_warm_command_target_without_fallback(hass, entry, cloud, failure):
    await setup(hass, entry)
    ids = entities(hass, entry)
    coordinator = entry.runtime_data.coordinator
    product = cloud.devices['switch-a']['productId']
    if failure == 'removed':
        del cloud.devices['switch-a']
    elif failure == 'unsupported':
        cloud.devices['switch-a']['deviceModel'] = 'camera'
    elif failure == 'schema':
        cloud.models[product]['properties'][1]['accessMode'] = 'r'
    else:
        cloud.model_failures[product] = '50000'
    await coordinator.async_refresh()
    cloud.calls.clear()
    with pytest.raises(HomeAssistantError, match='could not be confirmed'):
        await coordinator.async_set('switch-a', True, key=2)
    assert cloud.calls == []
    assert hass.states.get(ids[('switch-a', '127000')]).state == 'unavailable'
    assert hass.states.get(ids[('switch-b', '127000')]).state == 'on'
    if failure == 'schema':
        assert hass.states.get(ids[('switch-a', '11900')]).state == 'off'
        assert hass.states.get(ids[('switch-a', '127100')]).state == 'off'


async def test_state_read_failure_keeps_validated_target_writable(hass, entry, cloud):
    await setup(hass, entry)
    coordinator = entry.runtime_data.coordinator
    cloud.read_failures[('switch-a', '127000')] = '50000'
    await coordinator.async_refresh()
    cloud.read_failures.clear()
    cloud.calls.clear()
    await coordinator.async_set('switch-a', True, key=2)
    assert [api for api, _, _ in cloud.calls] == [
        'iot.control.SetIotProperties', 'iot.control.GetIotProperties']
    assert coordinator.data['switch-a']['127000']['api_state'] is True
