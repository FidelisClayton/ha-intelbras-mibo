"""Cloud polling keeps per-device failures separate from account failures."""
from datetime import timedelta

import pytest

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from tests.test_init import setup


def entities(hass, entry):
    return {r.unique_id.split(':')[-2]: r.entity_id
            for r in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)}


async def test_real_poll_uses_one_discovery_and_restores_device(hass, entry, cloud):
    await setup(hass, entry)
    ids = entities(hass, entry)
    cloud.calls.clear()
    cloud.states['switch-a'] = True
    cloud.read_failures['switch-b'] = '50000'
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=31))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get(ids['switch-a']).state == 'on'
    assert hass.states.get(ids['switch-b']).state == 'unavailable'
    assert sum(api == 'device.list.BasicList' for api, _, _ in cloud.calls) == 1
    assert not cloud.writes
    cloud.read_failures.clear()
    await entry.runtime_data.coordinator.async_refresh()
    assert hass.states.get(ids['switch-b']).state == 'on'


async def test_initial_unreadable_and_missing_devices_still_load(hass, entry, cloud):
    cloud.read_failures['switch-a'] = '50000'
    del cloud.devices['switch-b']
    await setup(hass, entry)
    ids = entities(hass, entry)
    assert len(ids) == 2
    assert all(hass.states.get(entity_id).state == 'unavailable' for entity_id in ids.values())


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
    assert hass.states.get(ids['switch-a']).state == 'off'
    assert hass.states.get(ids['switch-b']).state == 'on'


async def test_auth_invalid_refresh_requests_same_entry_reauth(hass, entry, cloud):
    await setup(hass, entry)
    cloud.read_failures['switch-a'] = '12112'
    await entry.runtime_data.coordinator.async_refresh()
    assert isinstance(entry.runtime_data.coordinator.last_exception, ConfigEntryAuthFailed)
    await hass.async_block_till_done()
    progress = hass.config_entries.flow.async_progress()
    assert len(progress) == 1
    assert progress[0]['context']['entry_id'] == entry.entry_id
