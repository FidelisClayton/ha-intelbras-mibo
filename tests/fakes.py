"""Synthetic cloud transport for tests of the native integration lifecycle."""
import io
import json
import threading


class Cloud:
    """Reply at the HTTP boundary while running the real protocol."""

    def __init__(self):
        self.devices = {key: {'deviceId': key, 'productId': 'test-product-' + key,
                             'deviceName': 'Test switch', 'deviceModel': 'EIW1003',
                             'channelList': [], 'channelNum': 0}
                        for key in ('switch-a', 'switch-b')}
        self.states = {device: {ref: value for ref in ('11900', '127000', '127100')}
                       for device, value in [('switch-a', False), ('switch-b', True)]}
        self.models = {device['productId']: {'properties': [
            {'identifier': identifier, 'ref': ref, 'dataType': {'type': 'bool'}, 'accessMode': 'rw'}
            for identifier, ref in [('switch', '11900'), ('std_switch2', '127000'),
                                    ('std_switch3', '127100')]]}
            for device in self.devices.values()}
        self.model_failures = {}
        self.read_failures = {}
        self.list_code = None
        self.list_failure = False
        self.write_failures = set()
        self.write_code = None
        self.confirm_writes = True
        self.calls = []
        self.write_started = None
        self.write_release = None

    def open(self, request, timeout):
        api = request.full_url.rsplit('/', 1)[-1]
        data = json.loads(request.data)['data']
        self.calls.append((api, data, threading.get_ident()))
        code, response = '10000', {}
        if api == 'device.list.BasicList':
            if self.list_failure:
                raise OSError('synthetic list transport failure')
            code = self.list_code or code
            response = {'deviceList': list(self.devices.values())}
        elif api == 'iot.manager.QueryModelInfo':
            code = self.model_failures.get(data['productId'], code)
            response = {'modelJson': self.models[data['productId']]}
        elif api == 'iot.control.GetIotProperties':
            device = data['deviceId']
            ref, = data['properties']
            code = self.read_failures.get((device, ref), code)
            value = self.states[device][ref]
            response = {'properties': {ref: int(value) if type(value) is bool else value}}
        elif api == 'iot.control.SetIotProperties':
            code = self.write_code or code
            if self.write_started:
                self.write_started.set()
                assert self.write_release.wait(10)
            ref, = data['properties']
            if (data['deviceId'], ref) in self.write_failures:
                raise OSError('synthetic transport failure')
            if self.confirm_writes and code == '10000':
                self.states[data['deviceId']][ref] = bool(data['properties'][ref])
        elif api == 'user.account.GetToken':
            response = {'username': 'test-user', 'token': 'test-token'}
        return io.BytesIO(json.dumps({'code': code, 'data': response}).encode())

    @property
    def writes(self):
        return [data for api, data, _ in self.calls if api == 'iot.control.SetIotProperties']
