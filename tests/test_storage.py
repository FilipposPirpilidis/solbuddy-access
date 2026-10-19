"""Native HA Store disk IO, restart, corruption, and lost-write defenses."""

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from homeassistant.core import CoreState
from homeassistant.util.file import WriteError

from custom_components.solbuddy_access.models import GrantStatus, ValidationError
from custom_components.solbuddy_access.storage import GrantStorage, StorageUnavailable


@pytest.fixture
def storage_id():
    return str(uuid4())


@pytest.fixture
async def storage(hass, storage_id):
    instance = GrantStorage(hass, storage_id)
    await instance.async_initialize()
    return instance


async def test_restart_persistence(hass, storage_id, storage, grant, now):
    await storage.async_add(grant)
    await storage.async_revoke(grant.grant_id, actor="owner", now=now)
    storage.close()
    restored = GrantStorage(hass, storage_id)
    await restored.async_load()
    assert restored.grants[0].status(now) is GrantStatus.REVOKED
    assert restored.grants[0].policies == grant.policies
    assert restored.grants[0].expires_at == grant.expires_at
    assert (
        await restored.async_revoke(grant.grant_id, actor="owner", now=now)
        == restored.grants[0]
    )


async def test_missing_store_never_initializes(hass, storage_id):
    storage = GrantStorage(hass, storage_id)
    with pytest.raises(StorageUnavailable):
        await storage.async_load()
    assert not storage.healthy
    with pytest.raises(StorageUnavailable):
        _ = storage.grants


async def test_initialization_preserves_corrupt_existing_file(hass, storage_id):
    path = Path(hass.config.path(".storage", f"solbuddy_access.{storage_id}"))

    def write_fixture():
        path.parent.mkdir(exist_ok=True)
        path.write_text("corrupt evidence")

    await hass.async_add_executor_job(write_fixture)
    storage = GrantStorage(hass, storage_id)
    with pytest.raises(StorageUnavailable):
        await storage.async_initialize()
    assert await hass.async_add_executor_job(path.read_text) == "corrupt evidence"


async def test_no_overwrite(storage):
    with pytest.raises(StorageUnavailable):
        await storage.async_initialize()
    assert not storage.healthy


@pytest.mark.parametrize("version,minor", [(1, 2), (2, 1), (True, 1), (1, True)])
async def test_unknown_envelope_never_migrated(hass, storage_id, version, minor):
    path = Path(hass.config.path(".storage", f"solbuddy_access.{storage_id}"))
    raw = json.dumps(
        {
            "key": f"solbuddy_access.{storage_id}",
            "version": version,
            "minor_version": minor,
            "data": {"revision": "test", "grants": []},
        }
    )

    def write_fixture():
        path.parent.mkdir(exist_ok=True)
        path.write_text(raw)

    await hass.async_add_executor_job(write_fixture)
    storage = GrantStorage(hass, storage_id)
    with pytest.raises(StorageUnavailable):
        await storage.async_load()
    assert await hass.async_add_executor_job(path.read_text) == raw


@pytest.mark.parametrize(
    "envelope",
    [
        "broken json",
        {"version": 2, "minor_version": 1, "data": {}},
        {"version": 1, "minor_version": 2, "data": {}},
        {
            "version": 1,
            "minor_version": 1,
            "data": {"revision": "test", "grants": [{"invalid": True}]},
        },
    ],
)
async def test_corrupt_or_future_storage(hass, storage_id, envelope):
    path = Path(hass.config.path(".storage", f"solbuddy_access.{storage_id}"))

    def write_fixture():
        path.parent.mkdir(exist_ok=True)
        path.write_text(envelope if isinstance(envelope, str) else json.dumps(envelope))

    await hass.async_add_executor_job(write_fixture)
    storage = GrantStorage(hass, storage_id)
    with pytest.raises(StorageUnavailable):
        await storage.async_load()
    assert not storage.healthy


async def test_swallowed_write_failure_blocks_repository(storage, grant):
    # Exercise native Store's real exception swallowing, not just our wrapper.
    with (
        patch(
            "homeassistant.helpers.storage.write_utf8_file_atomic",
            side_effect=WriteError("simulated disk failure"),
        ),
        pytest.raises(StorageUnavailable),
    ):
        await storage.async_add(grant)
    assert not storage.healthy
    with pytest.raises(StorageUnavailable):
        _ = storage.grants


async def test_revoke_failure_never_acknowledged(storage, grant, now):
    await storage.async_add(grant)
    with (
        patch.object(storage._store, "async_save", new=AsyncMock()),
        pytest.raises(StorageUnavailable),
    ):
        await storage.async_revoke(grant.grant_id, actor="owner", now=now)
    assert not storage.healthy


async def test_duplicate_and_concurrent_writes(storage, grant):
    second = replace(grant, grant_id=str(uuid4()))
    await asyncio.gather(storage.async_add(grant), storage.async_add(second))
    assert {g.grant_id for g in storage.grants} == {grant.grant_id, second.grant_id}
    with pytest.raises(ValidationError):
        await storage.async_add(grant)
    assert storage.healthy


async def test_cancellation_latches_failure(storage, grant):
    with patch.object(storage._store, "async_save", side_effect=asyncio.CancelledError):
        with pytest.raises(asyncio.CancelledError):
            await storage.async_add(grant)
    assert not storage.healthy


async def test_shutdown_refuses_deferred_save(hass, storage, grant):
    original = hass.state
    hass.set_state(CoreState.stopping)
    try:
        with pytest.raises(StorageUnavailable):
            await storage.async_add(grant)
    finally:
        hass.set_state(original)
