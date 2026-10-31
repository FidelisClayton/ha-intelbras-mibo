"""Native switch services publish only cloud-confirmed command outcomes."""
import asyncio
import threading
from unittest.mock import patch

import pytest
from homeassistant.exceptions import HomeAssistantError

from tests.test_coordinator import entities
from tests.test_init import setup


async def service(hass, entity_id, name):
    await hass.services.async_call('switch', name, {'entity_id': entity_id}, blocking=True)


async def test_completed_poll_cannot_revert_newer_native_command(hass, entry, cloud):
    await setup(hass, entry)
    entity_id = entities(hass, entry)[('switch-a', '11900')]
    coordinator = entry.runtime_data.coordinator
    cloud.calls.clear()
    poll_read, publish_poll = threading.Event(), threading.Event()
    executor_job = hass.async_add_executor_job
    delay_next = True

    def delayed_executor(job, *args):
        nonlocal delay_next
        if not delay_next:
            return executor_job(job, *args)
        delay_next = False

        def completed_io():
            # The real AccountRunner job has returned and released its thread
            # lock. Model a worker pause before its future delivers the result.
            result = job(*args)
            poll_read.set()
            assert publish_poll.wait(10)
            return result

        return executor_job(completed_io)

    with patch.object(hass, 'async_add_executor_job', delayed_executor):
        poll = asyncio.create_task(coordinator.async_refresh())
        command = None
        try:
            assert await asyncio.to_thread(poll_read.wait, 5)
            command = asyncio.create_task(service(hass, entity_id, 'turn_on'))
            # An ordering barrier may hold the command until the poll publishes.
            # Otherwise let the command finish before delivering the old poll.
            done, _ = await asyncio.wait({command}, timeout=1)
            assert not done, 'The command must wait for the pending poll publication.'
        finally:
            publish_poll.set()
            await poll
            if command is not None:
                await command

    assert cloud.states['switch-a']['11900'] is True
    assert hass.states.get(entity_id).state == 'on'
    assert len(cloud.writes) == 1
    assert [api for api, _, _ in cloud.calls][-2:] == [
        'iot.control.SetIotProperties', 'iot.control.GetIotProperties']
    assert cloud.writes[0]['properties'] == {'11900': 1}


@pytest.mark.parametrize("ref", ["11900", "127000", "127100"])
async def test_native_services_confirm_on_off_and_already_desired(hass, entry, cloud, ref):
    await setup(hass, entry)
    entity_id = entities(hass, entry)[('switch-a', ref)]
    cloud.calls.clear()
    await service(hass, entity_id, 'turn_on')
    assert [api for api, _, _ in cloud.calls] == ['iot.control.SetIotProperties', 'iot.control.GetIotProperties']
    assert cloud.writes[0]['properties'] == {ref: 1}
    assert type(cloud.writes[0]['properties'][ref]) is int
    assert hass.states.get(entity_id).state == 'on'
    assert all(not state for sibling, state in cloud.states['switch-a'].items() if sibling != ref)
    assert all(hass.states.get(entity).state == 'off'
               for (device, sibling), entity in entities(hass, entry).items()
               if device == 'switch-a' and sibling != ref)
    await service(hass, entity_id, 'turn_on')
    assert len(cloud.writes) == 2
    await service(hass, entity_id, 'turn_off')
    assert hass.states.get(entity_id).state == 'off'
    assert len(cloud.writes) == 3
    assert [api for api, _, _ in cloud.calls] == ['iot.control.SetIotProperties', 'iot.control.GetIotProperties'] * 3
    assert cloud.writes[-1]['properties'] == {ref: 0}
    assert type(cloud.writes[-1]['properties'][ref]) is int
    assert all(set(write['properties']) == {ref} for write in cloud.writes)
    assert cloud.states['switch-a'] == {'11900': False, '127000': False, '127100': False}


@pytest.mark.parametrize('ref', ['11900', '127000', '127100'])
async def test_uncertain_write_unavailable_without_replay_and_poll_recovers(hass, entry, cloud, ref):
    await setup(hass, entry)
    ids = entities(hass, entry)
    cloud.write_failures.add(('switch-a', ref))
    with pytest.raises(HomeAssistantError, match='could not be confirmed'):
        await service(hass, ids[('switch-a', ref)], 'turn_on')
    assert hass.states.get(ids[('switch-a', ref)]).state == 'unavailable'
    assert hass.states.get(ids[('switch-b', '11900')]).state == 'on'
    assert all(hass.states.get(entity).state == 'off'
               for (device, sibling), entity in entities(hass, entry).items()
               if device == 'switch-a' and sibling != ref)
    assert len(cloud.writes) == 1
    cloud.write_failures.clear()
    await entry.runtime_data.coordinator.async_refresh()
    assert hass.states.get(ids[('switch-a', ref)]).state == 'off'
    assert len(cloud.writes) == 1


@pytest.mark.parametrize('ref', ['11900', '127000', '127100'])
async def test_command_does_not_publish_optimistic_state(hass, entry, cloud, ref):
    await setup(hass, entry)
    entity_id = entities(hass, entry)[('switch-a', ref)]
    cloud.write_started, cloud.write_release = threading.Event(), threading.Event()
    task = asyncio.create_task(service(hass, entity_id, 'turn_on'))
    try:
        assert await asyncio.to_thread(cloud.write_started.wait, 5)
        assert hass.states.get(entity_id).state == 'off'
    finally:
        cloud.write_release.set()
    await task
    assert hass.states.get(entity_id).state == 'on'


@pytest.mark.parametrize('ref', ['11900', '127000', '127100'])
@pytest.mark.parametrize('stage', ['write', 'readback'])
async def test_command_auth_failure_starts_reauth_and_marks_account_unavailable(hass, entry, cloud, ref, stage):
    await setup(hass, entry)
    ids = entities(hass, entry)
    if stage == 'write':
        cloud.write_code = '12112'
    else:
        cloud.read_failures[('switch-a', ref)] = '12112'
    with pytest.raises(HomeAssistantError):
        await service(hass, ids[('switch-a', ref)], 'turn_on')
    assert all(hass.states.get(entity_id).state == 'unavailable' for entity_id in ids.values())
    assert len(cloud.writes) == 1
    await hass.async_block_till_done()
    assert hass.config_entries.flow.async_progress()[0]['context']['entry_id'] == entry.entry_id


@pytest.mark.parametrize('ref', ['11900', '127000', '127100'])
async def test_acknowledged_unconfirmed_command_is_not_replayed(hass, entry, cloud, ref):
    await setup(hass, entry)
    entity_id = entities(hass, entry)[('switch-a', ref)]
    cloud.confirm_writes = False
    with pytest.raises(HomeAssistantError, match='could not be confirmed'):
        await service(hass, entity_id, 'turn_on')
    assert hass.states.get(entity_id).state == 'unavailable'
    assert all(hass.states.get(entity).state == 'off'
               for (device, sibling), entity in entities(hass, entry).items()
               if device == 'switch-a' and sibling != ref)
    assert len(cloud.writes) == 1
    await entry.runtime_data.coordinator.async_refresh()
    assert hass.states.get(entity_id).state == 'off'
    assert len(cloud.writes) == 1
