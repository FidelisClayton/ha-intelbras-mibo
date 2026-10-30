"""Account-scoped executor jobs and token-only runtime reconstruction."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
import hashlib
import threading
from typing import Any, TypeVar

from homeassistant.core import HomeAssistant

from .bootstrap import async_load_app
from .protocol import Client

T = TypeVar('T')
_REGISTRY = 'intelbras_mibo_account_runners'


def canonical_account(email: str) -> str:
    """Use one identity for duplicates, serialization, and registry namespaces."""
    return email.strip().casefold()


def account_namespace(email: str) -> str:
    """Avoid publishing an account address in entity registry identifiers."""
    return hashlib.sha256(canonical_account(email).encode()).hexdigest()


class RuntimeClosed(Exception):
    """The owner has stopped accepting or publishing account work."""


@dataclass
class _AccountLock:
    lock: Any
    references: int = 0


class AccountRunner:
    """Lease a shared thread-owned account lock for complete synchronous jobs."""

    def __init__(self, hass: HomeAssistant, email: str) -> None:
        self.hass = hass
        self.account = canonical_account(email)
        registry = hass.data.setdefault(_REGISTRY, {})
        self._shared = registry.setdefault(self.account, _AccountLock(threading.Lock()))
        self._shared.references += 1
        self._closed = threading.Event()
        self._pending: set[asyncio.Future] = set()
        self._close_task: asyncio.Task | None = None

    @property
    def closed(self) -> bool:
        """Whether jobs and publications have stopped."""
        return self._closed.is_set()

    async def async_run(self, job: Callable[..., T], *args: Any) -> T:
        """Execute a whole operation without releasing its lock on cancellation."""
        if self.closed:
            raise RuntimeClosed

        def execute() -> T:
            with self._shared.lock:
                if self.closed:
                    raise RuntimeClosed
                return job(*args)

        future = self.hass.async_add_executor_job(execute)
        self._pending.add(future)

        def completed(done: asyncio.Future) -> None:
            self._pending.discard(done)
            # Retrieve errors even when the original awaiting flow was cancelled.
            if not done.cancelled():
                done.exception()

        future.add_done_callback(completed)
        result = await asyncio.shield(future)
        if self.closed:
            raise RuntimeClosed
        return result

    async def async_close(self) -> None:
        """Reject new jobs and wait for executor work before releasing the lease."""
        if self._close_task is None:
            self._closed.set()

            async def drain() -> None:
                if self._pending:
                    await asyncio.gather(*self._pending, return_exceptions=True)
                self._shared.references -= 1
                if self._shared.references == 0:
                    self.hass.data[_REGISTRY].pop(self.account)

            self._close_task = self.hass.async_create_task(drain())
        await asyncio.shield(self._close_task)


@dataclass
class AccountRuntime:
    """Client and runner owned by one loaded config entry."""

    client: Client
    runner: AccountRunner
    account_namespace: str

    async def async_close(self) -> None:
        """Stop and drain the entry before unload completes."""
        await self.runner.async_close()


async def async_create_runtime(hass: HomeAssistant, data: dict) -> AccountRuntime:
    """Restore a token session without ever retaining a password."""
    app = await async_load_app(hass)
    runner = AccountRunner(hass, data['email'])
    try:
        client = await runner.async_run(Client.from_session, app, data['session'])
    except BaseException:
        await runner.async_close()
        raise
    return AccountRuntime(client, runner, account_namespace(data['email']))
