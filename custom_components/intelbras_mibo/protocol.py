"""Bounded direct Mibo protocol, adapted from the MIT source named in NOTICE."""
import base64
import datetime
import hashlib
import hmac
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request

ENTRY = 'app-br.easy4ipcloud.com'
HOSTS = frozenset({ENTRY, 'app-sp2.easy4ipcloud.com'})
APIS = frozenset({'user.account.GetToken', 'user.account.Login',
                  'common.validcode.GetValidCode', 'user.account.GrantingCredit',
                  'device.list.BasicList', 'iot.manager.QueryModelInfo',
                  'iot.control.GetIotProperties', 'iot.control.SetIotProperties'})
LIMIT = 2 * 1024 * 1024


class MiboError(Exception):
    """Only a bounded identifier and explicitly safe command result cross this boundary."""
    def __init__(self, code, exit_code=5, result=None, *, invalidate_session=False):
        super().__init__(code)
        self.code, self.exit_code, self.result = code, exit_code, result
        self.invalidate_session = invalidate_session


def md5(value):
    return hashlib.md5(value.encode()).hexdigest()


def host_from(value):
    if not isinstance(value, str):
        raise MiboError('unapproved_entry_host')
    try:
        parsed = urllib.parse.urlsplit(value if '://' in value else 'https://' + value)
        port = parsed.port
    except ValueError:
        raise MiboError('unapproved_entry_host') from None
    if (parsed.scheme != 'https' or parsed.hostname not in HOSTS
            or port not in (None, 443) or parsed.username is not None
            or parsed.password is not None or parsed.path not in ('', '/')
            or parsed.query or parsed.fragment):
        raise MiboError('unapproved_entry_host')
    return parsed.hostname


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise MiboError('redirect_rejected')


def transport(url, body, headers):
    parsed = urllib.parse.urlsplit(url)
    host_from('https://' + parsed.netloc)
    if (parsed.scheme != 'https' or not parsed.path.startswith('/pcs/v1/')
            or parsed.path.removeprefix('/pcs/v1/') not in APIS or parsed.query or parsed.fragment):
        raise MiboError('endpoint_rejected')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    request = urllib.request.Request(url, body, headers, method='POST')
    try:
        with opener.open(request, timeout=20) as response:
            raw = response.read(LIMIT + 1)
    except urllib.error.HTTPError as error:
        raise MiboError('http_' + str(error.code)) from None
    except (urllib.error.URLError, OSError, ValueError):
        raise MiboError('transport_failure_no_retry') from None
    if len(raw) > LIMIT:
        raise MiboError('response_too_large')
    try:
        return json.loads(raw)
    except (ValueError, UnicodeError):
        raise MiboError('invalid_response') from None


class Client:
    def __init__(self, app, terminal, send=transport):
        self.app, self.terminal, self.send = app, terminal, send
        self.host, self.username, self.secret, self.session = ENTRY, '', '', None
        self.restored_session = False

    def auth(self, user, password):
        if user.startswith('token/'):
            user = 'uuid\\' + user[6:]
        elif user.startswith('default/'):
            user = 'default\\' + user[8:]
        self.username, self.secret = user, md5(password)

    def anonymous(self):
        self.session = None
        self.restored_session = False
        self.auth('default/' + self.app['defaultAK'], self.app['defaultSK'])

    def ua(self):
        return base64.b64encode(json.dumps({
            'clientType': 'phone', 'clientVersion': self.app['clientVersion'],
            'clientOV': 'Android 14', 'clientOS': 'Android', 'terminalModel': 'MiboMac',
            'terminalId': self.terminal, 'appid': self.app['appId'],
            'project': self.app['project'], 'language': 'pt_BR',
            'clientProtocolVersion': self.app['protocolVersion'],
            'timezoneOffset': str(-time.timezone), 'terminalBrand': 'Apple',
            'terminalName': 'Home Assistant', 'darkMode': 'light',
        }, sort_keys=True, separators=(',', ':')).encode()).decode()

    def call(self, api, data, content_type='application/json; charset=utf-8', version='191204',
             date=None, nonce=None):
        if api not in APIS or self.host not in HOSTS:
            raise MiboError('endpoint_rejected')
        path = '/pcs/v1/' + api
        body = json.dumps({'data': data}, separators=(',', ':'), ensure_ascii=False).encode()
        content_md5 = base64.b64encode(hashlib.md5(body).digest()).decode()
        headers = {'x-pcs-apiver': version, 'x-pcs-client-ua': self.ua(),
                   'x-pcs-date': date or datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                   'x-pcs-nonce': nonce or str(int(time.time()*1000)) + ''.join(secrets.choice('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789') for _ in range(32))}
        if self.session:
            headers['x-pcs-session-id'] = self.session
        headers['x-pcs-username'] = self.username
        canonical = 'POST\n' + path + '\n' + content_md5 + '\n' + content_type + '\n'
        canonical += ''.join(key + ':' + value + '\n' for key, value in headers.items())
        headers['x-pcs-signature'] = base64.b64encode(hmac.digest(self.secret.encode(), canonical.encode(), 'sha256')).decode()
        headers.update({'Content-Type': content_type, 'Content-MD5': content_md5})
        try:
            response = self.send('https://' + self.host + path, body, headers)
        except MiboError as error:
            if error.code == 'http_401':
                raise MiboError('login_required', 3, invalidate_session=self.restored_session) from None
            raise
        except Exception:
            raise MiboError('transport_failure_no_retry') from None
        if not isinstance(response, dict):
            raise MiboError('invalid_response')
        code = str(response.get('code', ''))
        if code == '12112' and self.restored_session:
            raise MiboError('login_required', 3, invalidate_session=True)
        if code != '10000':
            # Never emit server descriptions, which can echo credentials or IDs.
            raise MiboError('api_' + code if code.isascii() and code.isdigit() and len(code) <= 6 else 'api_invalid_code')
        data = response.get('data', {})
        if not isinstance(data, dict):
            raise MiboError('invalid_data')
        return data

    def login(self, email, password):
        self.host, self.session = ENTRY, None
        self.restored_session = False
        self.auth('account\\' + email, md5(password))
        token = self.call('user.account.GetToken', {'gpsInfo': {'latitude': 0.0, 'longitude': 0.0}})
        if token.get('failNum') not in (None, '', 0, '0'):
            raise MiboError('login_failure_no_retry')
        if not all(safe_text(token.get(key)) for key in ('username', 'token')):
            raise MiboError('invalid_login_response')
        if token.get('entryUrlV2'):
            self.host = host_from(token['entryUrlV2'])
        self.auth('token/' + token['username'], token['token'])
        self.session = token.get('sessionId')
        if self.session is not None and not safe_text(self.session):
            raise MiboError('invalid_login_response')
        self.token_username, self.token = token['username'], token['token']
        info = self.call('user.account.Login', {'timezoneOffset': -time.timezone // 60})
        if info.get('entryUrlV2'):
            self.host = host_from(info['entryUrlV2'])
        self.restored_session = True

    def mfa(self, email, code=None):
        self.anonymous()
        if code is None:
            return self.call('common.validcode.GetValidCode',
                             {'type': 'email', 'account': email, 'usage': 'GrantingCredit'},
                             'application/json', '61452')
        return self.call('user.account.GrantingCredit',
                         {'type': 'email', 'account': email, 'grantCreditAccount': email, 'validCode': code},
                         'application/json', '82197')

    def devices(self):
        devices, transfer, seen = [], '', set()
        for _ in range(50):
            data = self.call('device.list.BasicList', {'familyId': '', 'groupId': '', 'limit': 20,
                                                      'offset': 0, 'transferStr': transfer})
            batch = data.get('deviceList', [])
            if not isinstance(batch, list) or not all(isinstance(item, dict) for item in batch):
                raise MiboError('invalid_device_list')
            devices.extend(batch)
            transfer = data.get('transferStr', '')
            if not isinstance(transfer, str):
                raise MiboError('invalid_pagination')
            if data.get('hasNextPage') is True and (not transfer or not batch):
                raise MiboError('invalid_pagination')
            if not transfer or data.get('hasNextPage') is False or not batch:
                return devices
            if transfer in seen:
                raise MiboError('invalid_pagination')
            seen.add(transfer)
        raise MiboError('page_limit')

    def request_code(self, email):
        """Request terminal trust only after the caller observes api_12112."""
        return self.mfa(email)

    def grant_code(self, email, code):
        """Submit one code without resending email or retrying login."""
        if not isinstance(code, str) or not code.strip():
            raise MiboError('mfa_code_required', 3)
        return self.mfa(email, code)

    def export_session(self):
        """Return only validated token credentials suitable for an entry."""
        state = {'version': 1, 'username': getattr(self, 'token_username', None),
                 'token': getattr(self, 'token', None), 'session_id': self.session,
                 'host': self.host, 'terminal_id': self.terminal}
        return validate_session(state)

    @classmethod
    def from_session(cls, app, state, send=transport):
        validate_session(state)
        client = cls(app, state['terminal_id'], send)
        client.host = host_from(state['host'])
        client.auth('token/' + state['username'], state['token'])
        client.session = state.get('session_id')
        client.token_username, client.token = state['username'], state['token']
        client.restored_session = True
        return client


def safe_text(value):
    """Validate session/header values without retaining password material."""
    return (isinstance(value, str) and 0 < len(value) <= 4096
            and all(ord(char) >= 32 and ord(char) != 127 for char in value))


def validate_session(value):
    """Reject foreign storage shapes and unsafe token/header values."""
    fields = {'version', 'username', 'token', 'session_id', 'host', 'terminal_id'}
    if (not isinstance(value, dict) or set(value) != fields
            or type(value.get('version')) is not int or value['version'] != 1
            or not all(safe_text(value.get(key)) for key in ('username', 'token', 'terminal_id'))
            or value.get('session_id') is not None and not safe_text(value['session_id'])):
        raise MiboError('invalid_session', 3)
    host_from(value.get('host'))
    return dict(value)

KEYS = {1: ('switch', '11900'), 2: ('std_switch2', '127000'),
        3: ('std_switch3', '127100')}


def key_definition(key):
    if type(key) is not int or key not in KEYS:
        raise MiboError('unsupported_key', 4)
    return KEYS[key]

GET = 'iot.control.GetIotProperties'
SET = 'iot.control.SetIotProperties'
MODELS = frozenset({'IOT-EIW1003-IB', 'EIW1003'})


def model(device):
    return device.get('deviceModelName', device.get('deviceModel'))


def identity(device):
    if (not all(isinstance(device.get(k), str) and device[k] for k in ('deviceId', 'productId', 'deviceName'))
            or not isinstance(model(device), str) or model(device) not in MODELS):
        raise MiboError('unsupported_switch_identity', 4)
    if device.get('channelList') != [] or type(device.get('channelNum')) is not int or device['channelNum'] != 0:
        raise MiboError('unsupported_channel_metadata', 4)
    gray = device.get('grayFlag', '')
    if not isinstance(gray, str):
        raise MiboError('unsupported_switch_identity', 4)
    return {k: device[k] for k in ('deviceId', 'productId', 'deviceName')} | {'model': model(device), 'grayFlag': gray}


class Switches:
    def __init__(self, client, clock=time.monotonic, sleep=time.sleep):
        self.client, self.clock, self.sleep = client, clock, sleep

    def discover(self):
        """Return supported identities from one complete discovery snapshot.

        Invalid candidates are omitted independently. Duplicate cloud identities
        reject the snapshot because selecting either row would be ambiguous.
        """
        return parse_devices(self.client.devices())

    def _select(self, selector, devices=None):
        snapshot = self.discover() if devices is None else devices
        if selector not in snapshot:
            raise MiboError('unique_exact_switch_required', 4)
        return snapshot[selector]

    def _schema(self, selected):
        data = self.client.call('iot.manager.QueryModelInfo', {'productId': selected['productId'], 'grayFlag': selected['grayFlag']})
        schema = data.get('modelJson')
        try:
            schema = json.loads(schema) if isinstance(schema, str) else schema
        except ValueError:
            raise MiboError('unsupported_switch_schema', 4) from None
        props = schema.get('properties') if isinstance(schema, dict) else None
        if not isinstance(props, list) or not all(isinstance(p, dict) for p in props):
            raise MiboError('unsupported_switch_schema', 4)
        return props

    def _validate_schema(self, props, key):
        identifier, ref = key_definition(key)
        matches = [p for p in props if p.get('identifier') == identifier]
        references = [p for p in props if type(p.get('ref')) in (int, str)
                      and str(p['ref']) == ref]
        if len(matches) != 1 or len(references) != 1:
            raise MiboError('unsupported_switch_schema', 4)
        prop = matches[0]
        if (type(prop.get('ref')) not in (int, str) or str(prop['ref']) != ref
                or not isinstance(prop.get('dataType'), dict)
                or prop['dataType'].get('type') != 'bool' or prop.get('accessMode') != 'rw'):
            raise MiboError('unsupported_switch_schema', 4)

    def _body(self, selected, properties):
        return {'deviceId': selected['deviceId'], 'productId': selected['productId'], 'properties': properties}

    def _read(self, selected, key):
        _, ref = key_definition(key)
        data = self.client.call(GET, self._body(selected, [ref]), version='56906')
        props = data.get('properties')
        value = props.get(ref) if isinstance(props, dict) else None
        if type(value) is int and value in (0, 1):
            return value == 1
        if type(value) is str and value in ('0', '1'):
            return value == '1'
        raise MiboError('switch_state_not_binary', 4)

    def _result(self, selected, key):
        return {'device_id': selected['deviceId'], 'name': selected['deviceName'], 'key': key,
                'physical_verification': 'not_confirmed'}

    def status(self, selector, devices=None):
        """Read independently validated keys from one device model request."""
        selected = self._select(selector, devices)
        props = self._schema(selected)
        snapshots = {}
        for key, (_, ref) in KEYS.items():
            try:
                self._validate_schema(props, key)
                snapshots[ref] = self._result(selected, key) | {'api_state': self._read(selected, key)}
            except MiboError as error:
                if error.invalidate_session:
                    raise
                snapshots[ref] = None
        return snapshots

    def set(self, selector, desired, *, key=1):
        _, ref = key_definition(key)
        if type(desired) is not bool:
            raise MiboError('explicit_boolean_required', 4)
        selected = self._select(selector)
        self._validate_schema(self._schema(selected), key)
        current = self._read(selected, key)
        result = self._result(selected, key) | {'desired_state': desired, 'write_sent': False,
                    'command_acknowledged': False, 'api_state': current}
        if current == desired:
            return result
        if self._select(selected['deviceId']) != selected:
            raise MiboError('switch_identity_changed', 4)
        self._validate_schema(self._schema(selected), key)
        result.update(write_sent=True, api_state=None)
        try:
            self.client.call(SET, self._body(selected, {ref: int(desired)}), version='56906')
        except MiboError as error:
            if error.invalidate_session or error.code == 'login_required' or (error.code.startswith('api_') and error.code != 'api_invalid_code'):
                raise MiboError(error.code, error.exit_code, result, invalidate_session=error.invalidate_session) from None
            raise MiboError('write_outcome_uncertain', 6, result) from None
        except (Exception, KeyboardInterrupt):
            raise MiboError('write_outcome_uncertain', 6, result) from None
        result['command_acknowledged'] = True
        deadline = self.clock() + 5
        try:
            for attempt in range(3):
                if attempt:
                    remaining = deadline - self.clock()
                    if remaining <= 0:
                        break
                    self.sleep(min(2, remaining))
                    if self.clock() >= deadline:
                        break
                result['api_state'] = self._read(selected, key)
                if result['api_state'] == desired:
                    return result
                if self.clock() >= deadline:
                    break
        except MiboError as error:
            raise MiboError('accepted_state_unconfirmed', 6, result, invalidate_session=error.invalidate_session) from None
        except (Exception, KeyboardInterrupt):
            raise MiboError('accepted_state_unconfirmed', 6, result) from None
        raise MiboError('accepted_state_unconfirmed', 6, result)


def parse_devices(rows):
    """Parse one list result without any additional network requests."""
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise MiboError('invalid_device_list')
    result, seen = {}, set()
    for row in rows:
        device_id = row.get('deviceId')
        if isinstance(device_id, str) and device_id:
            if device_id in seen:
                raise MiboError('duplicate_switch_identity', 4)
            seen.add(device_id)
        try:
            selected = identity(row)
        except MiboError:
            continue
        result[selected['deviceId']] = selected
    return result
