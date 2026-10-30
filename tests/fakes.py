"""Synthetic cloud transport for tests of the native integration lifecycle."""
import io
import json
import threading


class Cloud:
    """Reply at the HTTP boundary while running the real protocol."""

    def __init__(self):
        self.devices = {key: {'deviceId': key, 'productId': 'test-product',
                             'deviceName': 'Test switch', 'deviceModel': 'EIW1003',
                             'channelList': [], 'channelNum': 0}
                        for key in ('switch-a', 'switch-b')}
        self.states = {'switch-a': False, 'switch-b': True}
        self.read_failures = {}
        self.list_code = None
        self.list_failure = False
        self.write_failure = False
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
            response = {'modelJson': {'properties': [{'identifier': 'switch', 'ref': '11900',
                         'dataType': {'type': 'bool'}, 'accessMode': 'rw'}]}}
        elif api == 'iot.control.GetIotProperties':
            key = data['deviceId']
            code = self.read_failures.get(key, code)
            response = {'properties': {'11900': int(self.states[key])}}
        elif api == 'iot.control.SetIotProperties':
            if self.write_started:
                self.write_started.set()
                assert self.write_release.wait(10)
            if self.write_failure:
                raise OSError('synthetic transport failure')
            if self.confirm_writes:
                self.states[data['deviceId']] = bool(data['properties']['11900'])
        elif api == 'user.account.GetToken':
            response = {'username': 'test-user', 'token': 'test-token'}
        return io.BytesIO(json.dumps({'code': code, 'data': response}).encode())

    @property
    def writes(self):
        return [data for api, data, _ in self.calls if api == 'iot.control.SetIotProperties']
