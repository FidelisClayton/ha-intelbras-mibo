"""Native account setup, email verification, and reauthentication."""

from uuid import uuid4

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .bootstrap import async_load_app
from .const import CONF_DEVICE_IDS, DOMAIN
from .protocol import Client, MiboError, Switches
from .runtime import AccountRunner, account_namespace, canonical_account


def _authentication_rejected(error):
    return (error.code in ('http_401', 'http_403', 'login_required', 'login_failure_no_retry') or
            error.code.startswith('api_') and error.code[4:].isdigit())


def _credentials(email=None):
    return vol.Schema({
        vol.Required('email', **({'default': email} if email else {})):
            selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.EMAIL)),
        vol.Required('password'):
            selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)),
    })


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
        self._code_verified = False

    @callback
    def async_remove(self):
        """Clear secrets on success, error abort, and explicit cancellation."""
        self._password = None
        self._client = None
        self._session = None
        self._code_verified = False
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

    async def _async_credentials(self, step, user_input, errors=None):
        errors = errors or {}
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
                self._code_verified = False
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
                        errors['base'] = ('invalid_auth' if self._client is not None and
                                          _authentication_rejected(error) else 'cannot_connect')
                else:
                    return await self._async_authenticated()
        return self.async_show_form(step_id=step, data_schema=_credentials(self._email), errors=errors)

    async def async_step_code(self, user_input=None):
        errors = {}
        if user_input is not None:
            code = user_input['code'].strip()
            if not self._code_verified:
                if not code:
                    errors['base'] = 'invalid_code'
                else:
                    try:
                        await self._runner.async_run(self._client.grant_code, self._email, code)
                    except MiboError as error:
                        errors['base'] = ('invalid_code' if error.code.startswith('api_')
                                          and error.code[4:].isdigit() else 'cannot_connect')
                    else:
                        self._code_verified = True
            if self._code_verified:
                try:
                    await self._runner.async_run(self._client.login, self._email, self._password)
                except MiboError as error:
                    if not _authentication_rejected(error):
                        errors['base'] = 'cannot_connect'
                    else:
                        self._password = None
                        return await self._async_credentials(
                            'reauth_confirm' if self._reauth else 'user', None,
                            {'base': 'invalid_auth'})
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
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title=self._email, data={
            'email': self._email, 'account': canonical_account(self._email),
            'account_namespace': account_namespace(self._email), 'session': self._session,
        }, options={CONF_DEVICE_IDS: list(self._devices)})
