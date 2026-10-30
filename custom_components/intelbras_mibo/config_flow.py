"""Native account setup, email verification, reauthentication, and selection."""

from uuid import uuid4

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .bootstrap import async_load_app
from .const import CONF_DEVICE_IDS, DOMAIN
from .protocol import Client, MiboError, Switches
from .runtime import AccountRunner, account_namespace, canonical_account


def _credentials(email=None):
    return vol.Schema({
        vol.Required('email', **({'default': email} if email else {})):
            selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.EMAIL)),
        vol.Required('password'):
            selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)),
    })


def _selection(devices, selected=()):
    options = [{'value': key, 'label': f"{row['deviceName']} ({key})"}
               for key, row in sorted(devices.items())]
    options.extend({'value': key, 'label': f'{key} (unavailable)'}
                   for key in sorted(set(selected) - devices.keys()))
    return vol.Schema({vol.Required(CONF_DEVICE_IDS, default=list(selected)):
                       selector.SelectSelector(selector.SelectSelectorConfig(
                           options=options, multiple=True,
                           mode=selector.SelectSelectorMode.LIST))})


def _valid_selection(user_input, available):
    values = user_input.get(CONF_DEVICE_IDS)
    return (isinstance(values, list) and bool(values)
            and all(isinstance(key, str) and key in available for key in values)
            and len(set(values)) == len(values))


class MiboConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure one account using only flow-local login credentials."""

    VERSION = 1

    def __init__(self):
        self._email = None
        self._password = None
        self._client = None
        self._runner = None
        self._app = None
        self._session = None
        self._devices = {}
        self._reauth = False
        self._terminal = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return MiboOptionsFlow()

    @callback
    def async_remove(self):
        """Clear secrets on success, error abort, and explicit cancellation."""
        self._password = None
        self._client = None
        self._session = None
        if self._runner is not None:
            self.hass.async_create_task(self._runner.async_close())
            self._runner = None

    async def async_step_user(self, user_input=None):
        return await self._async_credentials('user', user_input)

    async def async_step_reauth(self, entry_data):
        self._reauth = True
        entry = self._get_reauth_entry()
        self._email = entry.data['email']
        self._terminal = entry.data['session']['terminal_id']
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        return await self._async_credentials('reauth_confirm', user_input)

    async def _async_credentials(self, step, user_input):
        errors = {}
        if user_input is not None:
            email = user_input['email'].strip()
            if not email or '@' not in email or not user_input['password']:
                errors['base'] = 'invalid_auth'
            elif self._reauth and canonical_account(email) != canonical_account(self._email):
                errors['base'] = 'account_mismatch'
            else:
                await self.async_set_unique_id(canonical_account(email))
                if self._reauth:
                    self._abort_if_unique_id_mismatch()
                else:
                    self._abort_if_unique_id_configured()
                if self._runner is not None:
                    await self._runner.async_close()
                self._email = self._email if self._reauth else email
                self._password = user_input['password']
                self._client = None
                self._terminal = self._terminal or uuid4().hex
                self._runner = AccountRunner(self.hass, self._email)
                try:
                    self._app = await async_load_app(self.hass)
                    self._client = Client(self._app, self._terminal)
                    await self._runner.async_run(self._client.login, self._email, self._password)
                except MiboError as error:
                    if error.code == 'api_12112':
                        try:
                            await self._runner.async_run(self._client.request_code, self._email)
                        except MiboError:
                            self._password = None
                            errors['base'] = 'cannot_connect'
                        else:
                            return await self.async_step_code()
                    else:
                        self._password = None
                        errors['base'] = ('cannot_connect' if self._client is None or
                                          error.code == 'transport_failure_no_retry' else 'invalid_auth')
                else:
                    return await self._async_authenticated()
        return self.async_show_form(step_id=step, data_schema=_credentials(self._email), errors=errors)

    async def async_step_code(self, user_input=None):
        errors = {}
        if user_input is not None:
            code = user_input['code'].strip()
            if not code:
                errors['base'] = 'invalid_code'
            else:
                try:
                    client, email, password = self._client, self._email, self._password
                    def verify():
                        client.grant_code(email, code)
                        client.login(email, password)
                    await self._runner.async_run(verify)
                except MiboError:
                    errors['base'] = 'invalid_code'
                else:
                    return await self._async_authenticated()
        return self.async_show_form(step_id='code', errors=errors, data_schema=vol.Schema({
            vol.Required('code'): selector.TextSelector()}))

    async def _async_authenticated(self):
        self._password = None
        try:
            flow_client, app = self._client, self._app
            def discover():
                session = flow_client.export_session()
                # Mark subsequent 12112 responses as authenticated-session failures.
                client = Client.from_session(app, session)
                return session, client, Switches(client).discover()
            self._session, self._client, self._devices = await self._runner.async_run(discover)
        except MiboError as error:
            return self.async_abort(reason='invalid_auth' if error.invalidate_session else 'cannot_connect')
        if self._reauth:
            entry = self._get_reauth_entry()
            data = dict(entry.data)
            data['session'] = self._session
            return self.async_update_reload_and_abort(entry, data=data)
        if not self._devices:
            return self.async_abort(reason='no_supported_devices')
        return await self.async_step_devices()

    async def async_step_devices(self, user_input=None):
        errors = {}
        if user_input is not None:
            if _valid_selection(user_input, self._devices):
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=self._email, data={
                    'email': self._email, 'account': canonical_account(self._email),
                    'account_namespace': account_namespace(self._email), 'session': self._session,
                }, options={CONF_DEVICE_IDS: user_input[CONF_DEVICE_IDS]})
            errors['base'] = 'select_devices'
        return self.async_show_form(step_id='devices', data_schema=_selection(self._devices), errors=errors)


class MiboOptionsFlow(config_entries.OptionsFlow):
    """Rediscover choices without dropping previously selected missing devices."""

    def __init__(self):
        self._devices = None

    async def async_step_init(self, user_input=None):
        entry = self.config_entry
        selected = entry.options.get(CONF_DEVICE_IDS, [])
        if self._devices is None:
            runner = AccountRunner(self.hass, entry.data['email'])
            try:
                app = await async_load_app(self.hass)
                def discover():
                    client = Client.from_session(app, entry.data['session'])
                    return Switches(client).discover()
                self._devices = await runner.async_run(discover)
            except MiboError as error:
                return self.async_abort(reason='invalid_auth' if error.invalidate_session else 'cannot_connect')
            finally:
                await runner.async_close()
        errors = {}
        if user_input is not None:
            if _valid_selection(user_input, set(self._devices) | set(selected)):
                return self.async_create_entry(title='', data={CONF_DEVICE_IDS: user_input[CONF_DEVICE_IDS]})
            errors['base'] = 'select_devices'
        return self.async_show_form(step_id='init', errors=errors,
                                    data_schema=_selection(self._devices, selected))
