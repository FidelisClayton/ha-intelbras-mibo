"""Shared fixtures for isolated Home Assistant tests."""

import pytest


@pytest.fixture(autouse=True)
def custom_integrations(enable_custom_integrations):
    """Allow Home Assistant to discover the custom component."""
    yield


@pytest.fixture
def cloud(monkeypatch):
    """Replace network and immutable bootstrap inputs, leaving protocol real."""
    from unittest.mock import AsyncMock
    from custom_components.intelbras_mibo import protocol
    from tests.fakes import Cloud

    fake = Cloud()
    monkeypatch.setattr(protocol.urllib.request, 'build_opener', lambda *args: fake)
    app = {key: 'synthetic-' + key for key in ('appId', 'defaultAK', 'defaultSK',
                                             'clientVersion', 'project', 'protocolVersion')}
    monkeypatch.setattr('custom_components.intelbras_mibo.runtime.async_load_app', AsyncMock(return_value=app))
    monkeypatch.setattr('custom_components.intelbras_mibo.config_flow.async_load_app', AsyncMock(return_value=app))
    return fake


@pytest.fixture
def entry(hass):
    """A token-only entry with two selected synthetic switches."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from custom_components.intelbras_mibo.const import DOMAIN
    from custom_components.intelbras_mibo.runtime import account_namespace

    email = 'native@example.test'
    result = MockConfigEntry(domain=DOMAIN, unique_id=email, title=email,
                            data={'email': email, 'account': email,
                                  'account_namespace': account_namespace(email),
                                  'session': {'version': 1, 'username': 'test-user',
                                              'token': 'test-token', 'session_id': None,
                                              'host': 'app-br.easy4ipcloud.com',
                                              'terminal_id': 'test-terminal'}},
                            options={'device_ids': ['switch-a', 'switch-b']})
    result.add_to_hass(hass)
    return result
