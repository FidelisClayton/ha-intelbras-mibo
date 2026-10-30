"""Verified source parsing and Home Assistant private cache proofs."""
import hashlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.intelbras_mibo import bootstrap
from custom_components.intelbras_mibo.protocol import MiboError

APP = dict(appId='fixture-app', defaultAK='fixture-ak', defaultSK='fixture-sk', clientVersion='fixture-version', project='fixture-project', protocolVersion='fixture-protocol')
RAW = '\n'.join(f'private let {key} = "{value}"' for key, value in APP.items()).encode()


def test_verified_literal_extraction(monkeypatch):
    monkeypatch.setattr(bootstrap, 'SOURCE_SHA256', hashlib.sha256(RAW).hexdigest())
    assert bootstrap.extract_constants(RAW) == APP


@pytest.mark.parametrize('raw', [b'changed', RAW + b'\nlet appId = "duplicate"', b'let appId = "only"', RAW.replace(b'"fixture-app"', b'buildValue()'), RAW.replace(b'"fixture-app"', b'"\\(execute())"')])
def test_bad_source_fails_safely(raw, monkeypatch):
    monkeypatch.setattr(bootstrap, 'SOURCE_SHA256', hashlib.sha256(raw).hexdigest())
    with pytest.raises(MiboError):
        bootstrap.extract_constants(raw)


async def test_store_cache_and_executor(hass, monkeypatch):
    monkeypatch.setattr(bootstrap, 'SOURCE_SHA256', hashlib.sha256(RAW).hexdigest())
    download = MagicMock(return_value=RAW)
    monkeypatch.setattr(bootstrap, 'download_source', download)
    with patch.object(hass, 'async_add_executor_job', wraps=hass.async_add_executor_job) as executor:
        assert await bootstrap.async_load_app(hass) == APP
        assert executor.called
    download.assert_called_once()
    download.reset_mock()
    assert await bootstrap.async_load_app(hass) == APP
    download.assert_not_called()


async def test_invalid_cache_fetches_verified_replacement(hass, monkeypatch):
    monkeypatch.setattr(bootstrap, 'SOURCE_SHA256', hashlib.sha256(RAW).hexdigest())
    store = MagicMock()
    store.async_load = AsyncMock(return_value={'version': 1, 'source_url': bootstrap.SOURCE_URL, 'sha256': 'wrong', 'constants': APP})
    store.async_save = AsyncMock()
    with patch.object(bootstrap, 'Store', return_value=store), patch.object(bootstrap, 'download_source', return_value=RAW):
        assert await bootstrap.async_load_app(hass) == APP
    store.async_save.assert_awaited_once()


async def test_failed_cold_bootstrap_is_sanitized(hass):
    with patch.object(bootstrap, 'download_source', side_effect=OSError('PRIVATE')):
        with pytest.raises(MiboError, match='^bootstrap_download_failed$'):
            await bootstrap.async_load_app(hass)


def test_downloader_bounds_and_redirects():
    response = MagicMock()
    response.__enter__.return_value.read.return_value = b'x' * (bootstrap.LIMIT + 1)
    opener = MagicMock()
    opener.open.return_value = response
    with patch.object(bootstrap.urllib.request, 'build_opener', return_value=opener) as build:
        with pytest.raises(MiboError):
            bootstrap.download_source()
        assert build.call_args.args[0].proxies == {}
        assert opener.open.call_args.kwargs == {'timeout': 20}
        response.__enter__.return_value.read.assert_called_once_with(bootstrap.LIMIT + 1)


def test_digest_mismatch_is_rejected():
    with pytest.raises(MiboError, match='^bootstrap_digest_mismatch$'):
        bootstrap.extract_constants(RAW)


@pytest.mark.parametrize('changes', [
    {'version': True},
    {'source_url': 'https://example.test/other'},
    {'sha256': 'wrong'},
    {'constants': APP | {'extra': 'fixture-value'}},
    {'constants': APP | {'appId': 'unsafe\nvalue'}},
])
def test_cache_provenance_is_strict(changes):
    value = dict(version=1, source_url=bootstrap.SOURCE_URL,
                 sha256=bootstrap.SOURCE_SHA256, constants=APP)
    assert bootstrap.valid_cache(value)
    assert not bootstrap.valid_cache(value | changes)


async def test_bootstrap_does_not_log_constants(hass, monkeypatch, caplog):
    monkeypatch.setattr(bootstrap, 'SOURCE_SHA256', hashlib.sha256(RAW).hexdigest())
    monkeypatch.setattr(bootstrap, 'download_source', lambda: RAW)
    store = MagicMock()
    store.async_load = AsyncMock(return_value=None)
    store.async_save = AsyncMock()
    with patch.object(bootstrap, 'Store', return_value=store) as storage:
        assert await bootstrap.async_load_app(hass) == APP
    storage.assert_called_once_with(hass, 1, bootstrap.STORAGE_KEY, private=True)
    assert all(value not in caplog.text for value in APP.values())
