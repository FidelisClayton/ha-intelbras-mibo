"""Native forms use isolated account clients and token-only persistence."""
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import SOURCE_REAUTH, SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.intelbras_mibo.const import DOMAIN
from custom_components.intelbras_mibo.protocol import MiboError

EMAIL = 'user@example.test'
SESSION = {'version': 1, 'username': 'synthetic-user', 'token': 'synthetic-token',
           'session_id': None, 'host': 'app-br.easy4ipcloud.com', 'terminal_id': 'synthetic-terminal'}
DEVICES = {key: {'deviceId': key, 'productId': 'synthetic-product', 'deviceName': 'Switch',
                 'model': 'EIW1003', 'grayFlag': ''} for key in ('switch-a', 'switch-b')}


@pytest.fixture
def protocol():
    with (patch('custom_components.intelbras_mibo.config_flow.async_load_app', new_callable=AsyncMock) as app,
          patch('custom_components.intelbras_mibo.config_flow.Client') as client,
          patch('custom_components.intelbras_mibo.config_flow.Switches') as switches,
          patch('custom_components.intelbras_mibo.async_setup_entry', create=True, new_callable=AsyncMock, return_value=True)):
        client.return_value.export_session.return_value = SESSION.copy()
        client.from_session.return_value.export_session.return_value = SESSION.copy()
        switches.return_value.discover.return_value = DEVICES.copy()
        yield client, switches, app


async def start(hass, email=EMAIL):
    return await hass.config_entries.flow.async_init(DOMAIN, context={'source': SOURCE_USER},
                                                    data={'email': email, 'password': 'synthetic-password'})


async def test_user_selection_and_no_secrets(hass, protocol):
    client, switches, _ = protocol
    result = await start(hass)
    assert result['step_id'] == 'devices'
    choices = result['data_schema'].schema['device_ids'].config['options']
    assert {row['value'] for row in choices} == set(DEVICES)
    assert len({row['label'] for row in choices}) == 2
    empty = await hass.config_entries.flow.async_configure(result['flow_id'], {'device_ids': []})
    assert empty['errors'] == {'base': 'select_devices'}
    result = await hass.config_entries.flow.async_configure(result['flow_id'], {'device_ids': ['switch-a']})
    assert result['type'] == FlowResultType.CREATE_ENTRY
    assert result['options'] == {'device_ids': ['switch-a']}
    assert result['data']['session'] == SESSION
    assert result['result'].unique_id == EMAIL
    assert 'password' not in repr(result['data'])
    assert 'synthetic-password' not in repr(result)
    assert switches.call_args.args[0] is client.from_session.return_value


async def test_mfa_finite_stages_and_bad_code(hass, protocol):
    client, _, _ = protocol
    client.return_value.login.side_effect = [MiboError('api_12112'), None]
    result = await start(hass)
    assert result['step_id'] == 'code'
    client.return_value.request_code.assert_called_once_with(EMAIL)
    client.return_value.grant_code.side_effect = [MiboError('api_12345'), None]
    result = await hass.config_entries.flow.async_configure(result['flow_id'], {'code': 'bad'})
    assert result['step_id'] == 'code'
    assert result['errors'] == {'base': 'invalid_code'}
    assert client.return_value.login.call_count == 1
    result = await hass.config_entries.flow.async_configure(result['flow_id'], {'code': 'valid'})
    assert result['step_id'] == 'devices'
    assert client.return_value.login.call_count == 2
    client.return_value.request_code.assert_called_once()
    flow = hass.config_entries.flow._progress[result['flow_id']]
    assert flow._password is None
    hass.config_entries.flow.async_abort(result['flow_id'])
    await hass.async_block_till_done()
    assert flow._client is None
    assert flow._password is None


@pytest.mark.parametrize('code', ['api_12345', 'http_403', 'login_failure_no_retry'])
async def test_other_login_errors_never_request_mfa(hass, protocol, code):
    client, _, _ = protocol
    client.return_value.login.side_effect = MiboError(code)
    result = await start(hass)
    assert result['step_id'] == 'user'
    assert result['errors'] == {'base': 'invalid_auth'}
    client.return_value.request_code.assert_not_called()


async def test_duplicate_and_concurrent_flow(hass, protocol):
    result = await start(hass)
    duplicate = await start(hass, ' USER@EXAMPLE.TEST ')
    assert duplicate['reason'] == 'already_in_progress'
    result = await hass.config_entries.flow.async_configure(result['flow_id'], {'device_ids': ['switch-a']})
    duplicate = await start(hass)
    assert duplicate['reason'] == 'already_configured'


@pytest.mark.parametrize('failure,reason', [(MiboError('network_error'), 'cannot_connect'), (None, 'no_supported_devices')])
async def test_discovery_safe_failure(hass, protocol, failure, reason):
    _, switches, _ = protocol
    switches.return_value.discover.side_effect = failure
    switches.return_value.discover.return_value = {}
    result = await start(hass)
    assert result['reason'] == reason
    assert not hass.config_entries.async_entries(DOMAIN)


def existing(hass):
    entry = MockConfigEntry(domain=DOMAIN, unique_id=EMAIL, title=EMAIL,
                            data={'email': EMAIL, 'account': EMAIL, 'session': SESSION.copy()},
                            options={'device_ids': ['switch-a', 'missing-switch']})
    entry.add_to_hass(hass)
    return entry


async def test_reauth_preserves_account_terminal_and_options(hass, protocol):
    client, _, _ = protocol
    entry = existing(hass)
    old = dict(entry.data)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={'source': SOURCE_REAUTH, 'entry_id': entry.entry_id}, data=entry.data)
    assert result['step_id'] == 'reauth_confirm'
    result = await hass.config_entries.flow.async_configure(result['flow_id'], {'email': 'other@example.test', 'password': 'synthetic-password'})
    assert result['errors'] == {'base': 'account_mismatch'}
    assert dict(entry.data) == old
    with patch.object(hass.config_entries, 'async_schedule_reload') as reload:
        result = await hass.config_entries.flow.async_configure(result['flow_id'], {'email': EMAIL.upper(), 'password': 'synthetic-password'})
        assert result['reason'] == 'reauth_successful'
        reload.assert_called_once_with(entry.entry_id)
    assert client.call_args.args[1] == SESSION['terminal_id']
    assert entry.options['device_ids'] == ['switch-a', 'missing-switch']
    assert entry.unique_id == EMAIL


async def test_options_preserve_missing_and_reject_empty(hass, protocol):
    entry = existing(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result['step_id'] == 'init'
    choices = result['data_schema'].schema['device_ids'].config['options']
    assert {row['value'] for row in choices} == {*DEVICES, 'missing-switch'}
    result = await hass.config_entries.options.async_configure(result['flow_id'], {'device_ids': []})
    assert result['errors'] == {'base': 'select_devices'}
    result = await hass.config_entries.options.async_configure(result['flow_id'], {'device_ids': ['switch-b']})
    assert result['type'] == FlowResultType.CREATE_ENTRY
    assert entry.options == {'device_ids': ['switch-b']}


async def test_options_failure_leaves_prior_options(hass, protocol):
    _, switches, _ = protocol
    entry = existing(hass)
    switches.return_value.discover.side_effect = MiboError('network_error')
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result['reason'] == 'cannot_connect'
    assert entry.options == {'device_ids': ['switch-a', 'missing-switch']}


async def test_bootstrap_failure_and_hidden_password(hass, protocol):
    client, _, app = protocol
    result = await hass.config_entries.flow.async_init(DOMAIN, context={'source': SOURCE_USER})
    assert result['data_schema'].schema['password'].config['type'] == 'password'
    app.side_effect = MiboError('bootstrap_download_failed')
    result = await hass.config_entries.flow.async_configure(result['flow_id'], {'email': EMAIL, 'password': 'synthetic-password'})
    assert result['errors'] == {'base': 'cannot_connect'}
    client.assert_not_called()
    flow = hass.config_entries.flow._progress[result['flow_id']]
    assert flow._password is None
    hass.config_entries.flow.async_abort(result['flow_id'])
    await hass.async_block_till_done()
    assert flow._runner is None


async def test_empty_code_and_abort_clear_credentials(hass, protocol):
    client, _, _ = protocol
    client.return_value.login.side_effect = MiboError('api_12112')
    result = await start(hass)
    flow = hass.config_entries.flow._progress[result['flow_id']]
    result = await hass.config_entries.flow.async_configure(result['flow_id'], {'code': '  '})
    assert result['errors'] == {'base': 'invalid_code'}
    client.return_value.grant_code.assert_not_called()
    client.return_value.request_code.assert_called_once()
    hass.config_entries.flow.async_abort(result['flow_id'])
    await hass.async_block_till_done()
    assert flow._password is None
    assert flow._client is None
    assert not hass.config_entries.async_entries(DOMAIN)


async def test_failed_reauth_does_not_replace_loaded_client_or_data(hass, protocol):
    from types import SimpleNamespace
    client, _, _ = protocol
    entry = existing(hass)
    loaded_client = object()
    entry.runtime_data = SimpleNamespace(client=loaded_client)
    old_data = dict(entry.data)
    old_options = dict(entry.options)
    client.return_value.login.side_effect = [MiboError('api_12112'), MiboError('api_12345')]
    result = await hass.config_entries.flow.async_init(DOMAIN, context={'source': SOURCE_REAUTH, 'entry_id': entry.entry_id}, data=entry.data)
    result = await hass.config_entries.flow.async_configure(result['flow_id'], {'email': EMAIL, 'password': 'synthetic-password'})
    assert result['step_id'] == 'code'
    assert entry.runtime_data.client is loaded_client
    result = await hass.config_entries.flow.async_configure(result['flow_id'], {'code': 'synthetic-code'})
    assert result['errors'] == {'base': 'invalid_code'}
    assert entry.runtime_data.client is loaded_client
    assert dict(entry.data) == old_data
    assert dict(entry.options) == old_options
    assert client.call_args.args[1] == SESSION['terminal_id']
    hass.config_entries.flow.async_abort(result['flow_id'])
    await hass.async_block_till_done()


async def test_authenticated_discovery_rejection_does_not_start_mfa(hass, protocol):
    client, switches, _ = protocol
    switches.return_value.discover.side_effect = MiboError('login_required', invalidate_session=True)
    result = await start(hass)
    assert result['reason'] == 'invalid_auth'
    client.return_value.request_code.assert_not_called()
    assert not hass.config_entries.async_entries(DOMAIN)


async def test_protocol_filters_candidates_before_native_selection(hass, protocol):
    from custom_components.intelbras_mibo.protocol import parse_devices
    _, switches, _ = protocol
    rows = [{'deviceId': key, 'productId': 'synthetic-product', 'deviceName': 'Switch',
             'deviceModel': 'EIW1003', 'channelList': [], 'channelNum': 0}
            for key in ('switch-a', 'switch-b')]
    rows.extend([dict(rows[0], deviceId='camera-a', deviceModel='CAMERA'),
                 dict(rows[0], deviceId='invalid-switch', channelNum=True)])
    switches.return_value.discover.return_value = parse_devices(rows)
    result = await start(hass)
    choices = result['data_schema'].schema['device_ids'].config['options']
    assert {item['value'] for item in choices} == {'switch-a', 'switch-b'}
    hass.config_entries.flow.async_abort(result['flow_id'])
    await hass.async_block_till_done()
