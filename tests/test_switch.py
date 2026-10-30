"""Native switch services publish only cloud-confirmed command outcomes."""
import asyncio
import threading

import pytest
from homeassistant.exceptions import HomeAssistantError

from tests.test_coordinator import entities
from tests.test_init import setup


async def service(hass, entity_id, name):
    await hass.services.async_call('switch', name, {'entity_id': entity_id}, blocking=True)


async def test_native_services_confirm_on_off_and_noop(hass, entry, cloud):
    await setup(hass, entry)
    entity_id = entities(hass, entry)['switch-a']
    await service(hass, entity_id, 'turn_on')
    assert hass.states.get(entity_id).state == 'on'
    await service(hass, entity_id, 'turn_on')
    assert len(cloud.writes) == 1
    await service(hass, entity_id, 'turn_off')
    assert hass.states.get(entity_id).state == 'off'
    assert len(cloud.writes) == 2
    assert all(set(write['properties']) == {'11900'} for write in cloud.writes)


async def test_uncertain_write_unavailable_without_replay_and_poll_recovers(hass, entry, cloud):
    await setup(hass, entry)
    ids = entities(hass, entry)
    cloud.write_failure = True
    with pytest.raises(HomeAssistantError, match='could not be confirmed'):
        await service(hass, ids['switch-a'], 'turn_on')
    assert hass.states.get(ids['switch-a']).state == 'unavailable'
    assert hass.states.get(ids['switch-b']).state == 'on'
    assert len(cloud.writes) == 1
    cloud.write_failure = False
    await entry.runtime_data.coordinator.async_refresh()
    assert hass.states.get(ids['switch-a']).state == 'off'
    assert len(cloud.writes) == 1


async def test_command_does_not_publish_optimistic_state(hass, entry, cloud):
    await setup(hass, entry)
    entity_id = entities(hass, entry)['switch-a']
    cloud.write_started, cloud.write_release = threading.Event(), threading.Event()
    task = asyncio.create_task(service(hass, entity_id, 'turn_on'))
    try:
        assert await asyncio.to_thread(cloud.write_started.wait, 5)
        assert hass.states.get(entity_id).state == 'off'
    finally:
        cloud.write_release.set()
    await task
    assert hass.states.get(entity_id).state == 'on'


async def test_command_auth_failure_starts_reauth_and_marks_account_unavailable(hass, entry, cloud):
    await setup(hass, entry)
    ids = entities(hass, entry)
    cloud.list_code = '12112'
    with pytest.raises(HomeAssistantError):
        await service(hass, ids['switch-a'], 'turn_on')
    assert all(hass.states.get(entity_id).state == 'unavailable' for entity_id in ids.values())
    assert not cloud.writes
    await hass.async_block_till_done()
    assert hass.config_entries.flow.async_progress()[0]['context']['entry_id'] == entry.entry_id


async def test_acknowledged_unconfirmed_command_is_not_replayed(hass, entry, cloud):
    await setup(hass, entry)
    entity_id = entities(hass, entry)['switch-a']
    cloud.confirm_writes = False
    with pytest.raises(HomeAssistantError, match='could not be confirmed'):
        await service(hass, entity_id, 'turn_on')
    assert hass.states.get(entity_id).state == 'unavailable'
    assert len(cloud.writes) == 1
    await entry.runtime_data.coordinator.async_refresh()
    assert hass.states.get(entity_id).state == 'off'
    assert len(cloud.writes) == 1
