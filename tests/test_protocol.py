import base64
import hashlib
import hmac
import json
import unittest

import pytest
from unittest.mock import patch
from custom_components.intelbras_mibo.protocol import Client, MiboError, host_from
APP = dict(appId='fixture-app', defaultAK='fixture-ak', defaultSK='fixture-sk', clientVersion='fixture-version', project='fixture-project', protocolVersion='fixture-protocol')
def ok(data=None):
    return {'code': 10000, 'data': data or {}}
class Fake:
    def __init__(self, *responses):
        self.responses, self.requests = list(responses), []
    def __call__(self, url, body, headers):
        self.requests.append((url.rsplit('/', 1)[-1], json.loads(body)['data'], headers, body))
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response
class ClientTests(unittest.TestCase):
    def test_signing_known_canonical_double_md5(self):
        fake = Fake(ok())
        c = Client(APP, 'terminal', fake)
        c.auth('account\\a@example.test', hashlib.md5(b'password').hexdigest())
        with patch.object(c, 'ua', return_value='fixture-ua'):
            c.call('user.account.GetToken', {}, date='2026-10-30T00:00:00Z', nonce='fixture-nonce')
        _, _, headers, body = fake.requests[0]
        digest = base64.b64encode(hashlib.md5(body).digest()).decode()
        canonical = ('POST\n/pcs/v1/user.account.GetToken\n' + digest + '\napplication/json; charset=utf-8\nx-pcs-apiver:191204\nx-pcs-client-ua:fixture-ua\nx-pcs-date:2026-10-30T00:00:00Z\nx-pcs-nonce:fixture-nonce\nx-pcs-username:account\\a@example.test\n')
        key = hashlib.md5(hashlib.md5(b'password').hexdigest().encode()).hexdigest().encode()
        self.assertEqual(headers['x-pcs-signature'], base64.b64encode(hmac.digest(key, canonical.encode(), 'sha256')).decode())
        self.assertEqual(body, b'{"data":{}}')
    def test_staged_terminal_handshake_and_session(self):
        fake = Fake({'code': 12112}, ok(), ok(), ok({'username': 'id', 'token': 'TOKEN', 'sessionId': 'sid', 'failNum': 0}), ok())
        c = Client(APP, 'terminal', fake)
        with self.assertRaisesRegex(MiboError, 'api_12112'):
            c.login('email@example.test', 'PASSWORD')
        c.request_code('email@example.test')
        c.grant_code('email@example.test', '123456')
        c.login('email@example.test', 'PASSWORD')
        session = c.export_session()
        self.assertEqual([r[2]['x-pcs-apiver'] for r in fake.requests], ['191204', '61452', '82197', '191204', '191204'])
        self.assertNotIn('PASSWORD', json.dumps(session))
        self.assertNotIn('123456', json.dumps(session))
        restored = Client.from_session(APP, session, Fake(ok({'deviceList': []})))
        self.assertEqual(restored.devices(), [])
        self.assertEqual(restored.secret, hashlib.md5(b'TOKEN').hexdigest())
    def test_hosts_methods_malformed_pagination_fail_closed(self):
        for host in ['http://app-br.easy4ipcloud.com', 'app-br.easy4ipcloud.com:444', 'evil.test', 'app-br.easy4ipcloud.com/x', 'https://u@app-br.easy4ipcloud.com']:
            with self.assertRaises(MiboError):
                host_from(host)
        fake = Fake()
        with self.assertRaises(MiboError):
            Client(APP, 't', fake).call('arbitrary.Method', {})
        self.assertEqual(fake.requests, [])
        for response in [[], {'code': 10000, 'data': []}, {'code': 'secret-description'}]:
            with self.assertRaises(MiboError):
                Client(APP, 't', Fake(response)).call('device.list.BasicList', {})
        page = ok({'deviceList': [{}], 'transferStr': 'cursor'})
        fake = Fake(page, page)
        with self.assertRaises(MiboError):
            Client(APP, 't', fake).devices()
        self.assertEqual(len(fake.requests), 2)
        fake = Fake(*(ok({'deviceList': [{}], 'transferStr': str(i)}) for i in range(50)))
        with self.assertRaises(MiboError):
            Client(APP, 't', fake).devices()
        self.assertEqual(len(fake.requests), 50)
    def test_transport_bounds_no_proxy_redirect_and_timeout(self):
        from custom_components.intelbras_mibo.protocol import transport, NoRedirect, LIMIT
        from unittest.mock import MagicMock
        import urllib.error
        import urllib.request
        with self.assertRaises(MiboError):
            NoRedirect().redirect_request(None, None, 302, '', {}, 'https://evil.test')
        for raw in [b'x' * (LIMIT+1), b'not-json', b'\xff']:
            response = MagicMock()
            response.__enter__.return_value.read.return_value = raw
            opener = MagicMock()
            opener.open.return_value = response
            with patch('custom_components.intelbras_mibo.protocol.urllib.request.build_opener', return_value=opener) as build:
                with self.assertRaises(MiboError):
                    transport('https://app-br.easy4ipcloud.com/pcs/v1/device.list.BasicList', b'{}', {})
                self.assertEqual(opener.open.call_args.kwargs, {'timeout': 20})
                self.assertEqual(build.call_args.args[0].proxies, {})
                response.__enter__.return_value.read.assert_called_once_with(LIMIT+1)
        for url in ['https://app-br.easy4ipcloud.com/wrong', 'http://app-br.easy4ipcloud.com/pcs/v1/device.list.BasicList', 'https://evil.test/pcs/v1/device.list.BasicList']:
            with patch('custom_components.intelbras_mibo.protocol.urllib.request.build_opener') as build, self.assertRaises(MiboError):
                transport(url, b'{}', {})
            build.assert_not_called()
    def test_incomplete_pagination_does_not_return_partial_selection(self):
        fake = Fake(ok({'deviceList': [{'deviceId': 'partial'}], 'hasNextPage': True, 'transferStr': ''}))
        with self.assertRaises(MiboError):
            Client(APP, 't', fake).devices()
    def test_only_evidenced_auth_errors_invalidate_restored_session(self):
        state = dict(version=1, username='id', token='TOKEN', session_id=None,
                     host='app-br.easy4ipcloud.com', terminal_id='terminal')
        for failure, expected in [(MiboError('http_401'), True), ({'code': 12112}, True),
                                  (MiboError('http_403'), False), ({'code': 22001}, False),
                                  ({'code': 22005}, False), ({'code': 99999}, False)]:
            with self.subTest(failure=failure):
                client = Client.from_session(APP, state, Fake(failure))
                with self.assertRaises(MiboError) as error:
                    client.devices()
                self.assertEqual(error.exception.invalidate_session, expected)
                self.assertEqual(error.exception.exit_code, 3 if expected else 5)
    def test_fresh_login_auth_failure_preserves_existing_session(self):
        fake = Fake(MiboError('http_401'))
        with self.assertRaises(MiboError) as error:
            Client(APP, 'terminal', fake).login('e', 'PASSWORD')
        self.assertEqual(error.exception.exit_code, 3)
        self.assertFalse(error.exception.invalidate_session)

from custom_components.intelbras_mibo.protocol import Switches
D = dict(deviceId='id-1', productId='product-1', deviceName='Fixture switch', deviceModelName='IOT-EIW1003-IB', channelList=[], channelNum=0)
SCHEMA = {'modelJson': {'properties': [{'identifier': 'switch', 'ref': 11900, 'dataType': {'type': 'bool'}, 'accessMode': 'rw'}]}}
def devices(*rows):
    return ok({'deviceList': list(rows)})
def state(value, ref="11900"):
    return ok({"properties": {ref: value}})
class SwitchTests(unittest.TestCase):
    def switches(self, fake):
        return Switches(Client(APP, 't', fake), sleep=lambda _: None)
    def test_absolute_single_write_contract_and_idempotence(self):
        for key, identifier, ref in [(1, 'switch', '11900'), (2, 'std_switch2', '127000'),
                                     (3, 'std_switch3', '127100')]:
            schema = {'modelJson': {'properties': [{'identifier': identifier, 'ref': ref,
                       'dataType': {'type': 'bool'}, 'accessMode': 'rw'}]}}
            fake = Fake(devices(D), ok(schema), state(1, ref), devices(D), ok(schema), ok(), state('0', ref))
            result = self.switches(fake).set('id-1', False, key=key)
            writes = [r for r in fake.requests if r[0] == 'iot.control.SetIotProperties']
            self.assertEqual(len(writes), 1)
            self.assertEqual(writes[0][1], {'deviceId': 'id-1', 'productId': 'product-1', 'properties': {ref: 0}})
            self.assertIs(type(writes[0][1]['properties'][ref]), int)
            self.assertEqual(writes[0][2]['x-pcs-apiver'], '56906')
            self.assertTrue(result['command_acknowledged'])
            self.assertIs(result['api_state'], False)
            fake = Fake(devices(D), ok(schema), state(0, ref))
            self.assertFalse(self.switches(fake).set('id-1', False, key=key)['write_sent'])
            self.assertEqual(len(fake.requests), 3)
    def test_uncertain_or_unconfirmed_never_rewrites(self):
        for key, identifier, ref in [(1, 'switch', '11900'), (2, 'std_switch2', '127000'),
                                     (3, 'std_switch3', '127100')]:
            schema = {'modelJson': {'properties': [{'identifier': identifier, 'ref': ref,
                       'dataType': {'type': 'bool'}, 'accessMode': 'rw'}]}}
            for tail in [(TimeoutError(),), (ok(), state(1, ref), state(1, ref), state(1, ref)), (ok(), ValueError('PRIVATE'))]:
                fake = Fake(devices(D), ok(schema), state(1, ref), devices(D), ok(schema), *tail)
                with self.assertRaises(MiboError) as error:
                    self.switches(fake).set('id-1', False, key=key)
                self.assertEqual(error.exception.exit_code, 6)
                self.assertEqual(sum(r[0].endswith('SetIotProperties') for r in fake.requests), 1)
                self.assertNotIn('PRIVATE', str(error.exception))
                if not isinstance(tail[0], BaseException):
                    self.assertTrue(error.exception.result['command_acknowledged'])
    def test_ambiguous_metadata_schema_invalid_values_block_write(self):
        for rows in [(D, D), ({**D, 'channelNum': False},), ({**D, 'deviceModelName': 'camera'},), ({**D, 'productId': ''},)]:
            fake = Fake(devices(*rows))
            with self.assertRaises(MiboError):
                self.switches(fake).set('id-1', False, key=1)
            self.assertEqual(len(fake.requests), 1)
        for prop in [{}, {'identifier': 'switch', 'ref': 11901, 'dataType': {'type': 'bool'}, 'accessMode': 'rw'}]:
            fake = Fake(devices(D), ok({'modelJson': {'properties': [prop]}}))
            with self.assertRaises(MiboError):
                self.switches(fake).set('id-1', True, key=1)
            self.assertEqual(len(fake.requests), 2)
        for value in [True, None, 2, 'true', {}]:
            self.assertIsNone(self.switches(Fake(devices(D), ok(SCHEMA), state(value))).status('id-1')['11900'])
        for key in [True, False, 0, 4, '2', 2.0, None, 126900]:
            fake = Fake()
            with self.assertRaisesRegex(MiboError, 'unsupported_key'):
                self.switches(fake).set('id-1', True, key=key)
            self.assertEqual(fake.requests, [])

    def test_id_wins_and_identity_revalidation(self):
        other = {**D, 'deviceId': 'other', 'deviceName': 'id-1'}
        fake = Fake(devices(D, other), ok(SCHEMA), state(0))
        self.assertEqual(self.switches(fake).status('id-1')['11900']['device_id'], 'id-1')
        fake = Fake(devices(D), ok(SCHEMA), state(1), devices({**D, 'productId': 'changed'}))
        with self.assertRaises(MiboError):
            self.switches(fake).set('id-1', False, key=1)
        self.assertEqual(len(fake.requests), 4)
    def test_schema_allows_bool_metadata_and_preserves_gray_flag(self):
        device = {**D, 'grayFlag': 'fixture-gray'}
        schema = {'modelJson': {'properties': [{'identifier': 'switch', 'ref': '11900', 'dataType': {'type': 'bool', 'specs': {'0': 'off', '1': 'on'}}, 'accessMode': 'rw'}]}}
        fake = Fake(devices(device), ok(schema), state(1))
        self.assertTrue(self.switches(fake).status('id-1')['11900']['api_state'])
        self.assertEqual(fake.requests[1][1], {'productId': 'product-1', 'grayFlag': 'fixture-gray'})
    def test_provider_rejection_is_distinct_from_transport_uncertainty(self):
        fake = Fake(devices(D), ok(SCHEMA), state(1), devices(D), ok(SCHEMA), {'code': 22001, 'desc': 'PRIVATE'})
        with self.assertRaises(MiboError) as error:
            self.switches(fake).set('id-1', False, key=1)
        self.assertEqual(error.exception.code, 'api_22001')
        self.assertEqual(error.exception.exit_code, 5)
        self.assertTrue(error.exception.result['write_sent'])
        self.assertFalse(error.exception.result['command_acknowledged'])
        self.assertEqual(len(fake.requests), 6)
    def test_discovery_uses_ids_and_excludes_invalid_rows(self):
        invalid = {**D, 'deviceId': 'bad', 'channelNum': False}
        other = {**D, 'deviceId': 'other'}
        switches = self.switches(Fake(devices(invalid, D, other)))
        self.assertEqual(set(switches.discover()), {'id-1', 'other'})
        with self.assertRaisesRegex(MiboError, 'duplicate_switch_identity'):
            self.switches(Fake(devices(D, D))).discover()
        fake = Fake(devices(D))
        with self.assertRaisesRegex(MiboError, 'unique_exact_switch_required'):
            self.switches(fake).status('Fixture switch')

    def test_shared_discovery_avoids_repeated_list_requests(self):
        fake = Fake(devices(D), ok(SCHEMA), state(1), ok(SCHEMA), state(0))
        switches = self.switches(fake)
        discovery = switches.discover()
        self.assertTrue(switches.status('id-1', discovery)['11900']['api_state'])
        self.assertFalse(switches.status('id-1', discovery)['11900']['api_state'])
        self.assertEqual(sum(r[0] == 'device.list.BasicList' for r in fake.requests), 1)

    def test_auth_invalidation_survives_control_result_without_losing_ack(self):
        session = dict(version=1, username='id', token='TOKEN', session_id=None,
                       host='app-br.easy4ipcloud.com', terminal_id='terminal')
        for responses, code, acknowledged in [([MiboError('http_401')], 3, False),
                                                ([ok(), MiboError('http_401')], 6, True)]:
            fake = Fake(devices(D), ok(SCHEMA), state(1), devices(D), ok(SCHEMA), *responses)
            switches = Switches(Client.from_session(APP, session, fake), sleep=lambda _: None)
            with self.assertRaises(MiboError) as error:
                switches.set('id-1', False, key=1)
            self.assertEqual(error.exception.exit_code, code)
            self.assertTrue(error.exception.invalidate_session)
            self.assertEqual(error.exception.result['command_acknowledged'], acknowledged)
            self.assertEqual(sum(r[0].endswith('SetIotProperties') for r in fake.requests), 1)

    def test_malformed_candidate_does_not_hide_valid_device(self):
        for changed in [{'deviceModelName': []}, {'channelList': None}, {'grayFlag': 4}, {'deviceId': []}]:
            with self.subTest(changed=changed):
                invalid = {**D, 'deviceId': 'bad', **changed}
                self.assertEqual(set(self.switches(Fake(devices(invalid, D))).discover()), {'id-1'})

    def test_string_schema_and_missing_gray_flag(self):
        fake = Fake(devices(D), ok({'modelJson': json.dumps(SCHEMA['modelJson'])}), state('1'))
        self.assertTrue(self.switches(fake).status('id-1')['11900']['api_state'])
        self.assertEqual(fake.requests[1][1], {'productId': 'product-1', 'grayFlag': ''})
        self.assertEqual(fake.requests[2][1], {'deviceId': 'id-1', 'productId': 'product-1', 'properties': ['11900']})

    def test_schema_change_before_write_blocks_command(self):
        for key, identifier, ref in [(1, 'switch', '11900'), (2, 'std_switch2', '127000'),
                                     (3, 'std_switch3', '127100')]:
            schema = {'modelJson': {'properties': [{'identifier': identifier, 'ref': ref,
                       'dataType': {'type': 'bool'}, 'accessMode': 'rw'}]}}
            bad_schema = {'modelJson': {'properties': []}}
            fake = Fake(devices(D), ok(schema), state(0, ref), devices(D), ok(bad_schema))
            with self.assertRaisesRegex(MiboError, 'unsupported_switch_schema'):
                self.switches(fake).set('id-1', True, key=key)
            self.assertFalse(any(r[0] == 'iot.control.SetIotProperties' for r in fake.requests))

    def test_nonboolean_writes_do_not_touch_network(self):
        for key in [1, 2, 3]:
            for desired in [0, 1, 'on', None]:
                fake = Fake()
                with self.assertRaisesRegex(MiboError, 'explicit_boolean_required'):
                    self.switches(fake).set('id-1', desired, key=key)
                self.assertEqual(fake.requests, [])

    def test_confirmation_stops_after_polling_deadline(self):
        fake = Fake(devices(D), ok(SCHEMA), state(0), devices(D), ok(SCHEMA), ok(), state(0))
        now = [0]
        def advance(_):
            now[0] = 5
        switches = Switches(Client(APP, 't', fake), clock=lambda: now[0], sleep=advance)
        with self.assertRaisesRegex(MiboError, 'accepted_state_unconfirmed'):
            switches.set('id-1', True)
        self.assertEqual(sum(r[0] == 'iot.control.GetIotProperties' for r in fake.requests), 2)


class SessionTests(unittest.TestCase):
    def test_invalid_saved_session_never_sends(self):
        base = dict(version=1, username='id', token='TOKEN', session_id=None,
                    host='app-br.easy4ipcloud.com', terminal_id='terminal')
        for changes in [{'password': 'PRIVATE'}, {'version': True}, {'token': ''}, {'token': 'x\nheader'}, {'host': 'evil.test'}, {'session_id': False}]:
            fake = Fake()
            with self.assertRaises(MiboError):
                Client.from_session(APP, base | changes, fake)
            self.assertEqual(fake.requests, [])

    def test_fresh_token_header_injection_rejected_before_login(self):
        for key in ['username', 'token', 'sessionId']:
            token = {'username': 'id', 'token': 'TOKEN', 'sessionId': 'sid', key: 'x\nPRIVATE'}
            fake = Fake(ok(token))
            with self.assertRaisesRegex(MiboError, 'invalid_login_response'):
                Client(APP, 'terminal', fake).login('email@example.test', 'PASSWORD')
            self.assertEqual(len(fake.requests), 1)


@pytest.mark.parametrize('string_model', [False, True])
@pytest.mark.parametrize('ref_type', [int, str])
@pytest.mark.parametrize('invalid', ['missing', 'identifier', 'duplicate_identifier', 'duplicate_ref',
                                    'wrong_ref', 'bool_ref', 'type', 'access'])
def test_invalid_key_metadata_isolated_and_blocks_write(string_model, ref_type, invalid):
    props = [{'identifier': identifier, 'ref': ref_type(ref),
              'dataType': {'type': 'bool'}, 'accessMode': 'rw'}
             for identifier, ref in [('switch', '11900'), ('std_switch2', '127000'),
                                     ('std_switch3', '127100')]]
    if invalid == 'missing':
        props.pop(1)
    elif invalid == 'identifier':
        props[1]['identifier'] = 'unknown'
    elif invalid == 'duplicate_identifier':
        props.append({**props[1], 'ref': '99999'})
    elif invalid == 'duplicate_ref':
        props.append({**props[1], 'identifier': 'unknown'})
    elif invalid == 'wrong_ref':
        props[1]['ref'] = '126900'
    elif invalid == 'bool_ref':
        props[1]['ref'] = True
    elif invalid == 'type':
        props[1]['dataType'] = {'type': 'int'}
    else:
        props[1]['accessMode'] = 'r'
    model = {'properties': props}
    schema = {'modelJson': json.dumps(model) if string_model else model}
    fake = Fake(devices(D), ok(schema), state(1), state('0', '127100'))
    result = Switches(Client(APP, 't', fake)).status('id-1')
    assert result['11900']['api_state'] is True
    assert result['127000'] is None
    assert result['127100']['api_state'] is False
    assert [r[1]['properties'] for r in fake.requests if r[0].endswith('GetIotProperties')] == [
        ['11900'], ['127100']]
    fake = Fake(devices(D), ok(schema))
    with pytest.raises(MiboError, match='unsupported_switch_schema'):
        Switches(Client(APP, 't', fake)).set('id-1', True, key=2)
    assert len(fake.requests) == 2


@pytest.mark.parametrize('key,identifier,ref', [(1, 'switch', '11900'),
                                              (2, 'std_switch2', '127000'),
                                              (3, 'std_switch3', '127100')])
@pytest.mark.parametrize('value', [True, None, 2, -1, 0.0, 'true', {}, []])
def test_each_key_strict_binary_reads(key, identifier, ref, value):
    schema = {'modelJson': {'properties': [{'identifier': identifier, 'ref': ref,
               'dataType': {'type': 'bool'}, 'accessMode': 'rw'}]}}
    fake = Fake(devices(D), ok(schema), state(value, ref))
    assert Switches(Client(APP, 't', fake)).status('id-1')[ref] is None
    fake = Fake(devices(D), ok(schema), state(value, ref))
    with pytest.raises(MiboError, match='switch_state_not_binary'):
        Switches(Client(APP, 't', fake)).set('id-1', True, key=key)
    assert not any(r[0].endswith('SetIotProperties') for r in fake.requests)


@pytest.mark.parametrize('value', [0, 1, '0', '1'])
def test_three_key_string_schema_parsed_once_and_read_separately(value):
    model = json.dumps({'properties': [
        {'identifier': identifier, 'ref': ref, 'dataType': {'type': 'bool'}, 'accessMode': 'rw'}
        for identifier, ref in [('switch', '11900'), ('std_switch2', '127000'),
                                ('std_switch3', '127100')]]})
    fake = Fake(devices(D), ok({'modelJson': model}),
                *(state(value, ref) for ref in ['11900', '127000', '127100']))
    with patch('custom_components.intelbras_mibo.protocol.json.loads', wraps=json.loads) as parse:
        result = Switches(Client(APP, 't', fake)).status('id-1')
    assert sum(call.args == (model,) for call in parse.call_args_list) == 1
    assert set(result) == {'11900', '127000', '127100'}
    assert [snapshot['key'] for snapshot in result.values()] == [1, 2, 3]
    assert all(snapshot['api_state'] is (str(value) == '1') for snapshot in result.values())
    assert [r[0] for r in fake.requests].count('iot.manager.QueryModelInfo') == 1
    reads = [r for r in fake.requests if r[0] == 'iot.control.GetIotProperties']
    assert [r[1]['properties'] for r in reads] == [['11900'], ['127000'], ['127100']]
    assert all(r[2]['x-pcs-apiver'] == '56906' for r in reads)
