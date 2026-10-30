"""Account jobs retain serialization across cancellation and unload."""
import asyncio
import threading

import pytest

from custom_components.intelbras_mibo.runtime import AccountRunner, RuntimeClosed, account_namespace


async def test_same_account_serialized_after_cancellation_and_close(hass):
    first = AccountRunner(hass, ' User@example.test ')
    second = AccountRunner(hass, 'user@EXAMPLE.test')
    entered, release, followed = threading.Event(), threading.Event(), threading.Event()

    def blocking():
        entered.set()
        assert release.wait(5)
        return 'late'

    task = asyncio.create_task(first.async_run(blocking))
    await asyncio.to_thread(entered.wait, 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    close = asyncio.create_task(first.async_close())
    queued = asyncio.create_task(second.async_run(followed.set))
    await asyncio.sleep(0)
    assert not close.done()
    assert not followed.is_set()
    with pytest.raises(RuntimeClosed):
        await first.async_run(lambda: None)
    release.set()
    await close
    await queued
    assert followed.is_set()
    await second.async_close()
    assert account_namespace(' User@example.test ') == account_namespace('user@example.test')


async def test_close_prevents_late_publication(hass):
    runner = AccountRunner(hass, 'other@example.test')
    entered, release = threading.Event(), threading.Event()

    def blocking():
        entered.set()
        assert release.wait(5)
        return 42

    task = asyncio.create_task(runner.async_run(blocking))
    await asyncio.to_thread(entered.wait, 5)
    close = asyncio.create_task(runner.async_close())
    await asyncio.sleep(0)
    release.set()
    with pytest.raises(RuntimeClosed):
        await task
    await close


async def test_cancelled_close_still_drains_and_keeps_account_lease(hass):
    runner = AccountRunner(hass, 'user@example.test')
    entered, release = threading.Event(), threading.Event()
    def blocking():
        entered.set()
        assert release.wait(5)
    work = asyncio.create_task(runner.async_run(blocking))
    await asyncio.to_thread(entered.wait, 5)
    close = asyncio.create_task(runner.async_close())
    await asyncio.sleep(0)
    close.cancel()
    with pytest.raises(asyncio.CancelledError):
        await close
    replacement = AccountRunner(hass, ' USER@example.test ')
    followed = threading.Event()
    next_work = asyncio.create_task(replacement.async_run(followed.set))
    await asyncio.sleep(0)
    assert not followed.is_set()
    release.set()
    with pytest.raises(RuntimeClosed):
        await work
    await runner.async_close()
    await next_work
    await replacement.async_close()


async def test_runtime_restores_token_session(hass):
    from unittest.mock import AsyncMock, patch
    from custom_components.intelbras_mibo.runtime import async_create_runtime
    session = {'version': 1, 'username': 'synthetic-user', 'token': 'synthetic-token',
               'session_id': None, 'host': 'app-br.easy4ipcloud.com', 'terminal_id': 'synthetic-terminal'}
    with (patch('custom_components.intelbras_mibo.runtime.async_load_app', new_callable=AsyncMock) as app,
          patch('custom_components.intelbras_mibo.runtime.Client.from_session') as restore):
        runtime = await async_create_runtime(hass, {'email': 'user@example.test', 'session': session})
        restore.assert_called_once_with(app.return_value, session)
        assert runtime.client is restore.return_value
        assert runtime.account_namespace == account_namespace('user@example.test')
        await runtime.async_close()
