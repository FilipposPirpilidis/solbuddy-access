"""Versioned native storage with serialized writes and verified persistence."""

import asyncio
import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

from homeassistant.core import CoreState, HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN, MAX_GRANTS, STORAGE_VERSION
from .models import Grant, ValidationError, require_keys, require_text, require_time


class StorageUnavailable(RuntimeError):
    """Security state cannot be trusted. Do not expose underlying data/errors."""


class GrantStorage:
    """Internal repository, not an administrative API or authorization boundary.

    Native Store logs and swallows some write errors in HA 2026.10.2. Verify
    the actual file after every save; merely awaiting async_save is insufficient.
    No migration is defined: validate versions before native Store can migrate.
    """

    def __init__(self, hass: HomeAssistant, storage_id: str) -> None:
        require_text(storage_id)
        if str(UUID(storage_id)) != storage_id:
            raise ValidationError("Invalid storage ID")
        self._hass = hass
        self._store = Store[dict](
            hass,
            STORAGE_VERSION,
            f"{DOMAIN}.{storage_id}",
            private=True,
            atomic_writes=True,
        )
        self._lock = asyncio.Lock()
        self._grants: tuple[Grant, ...] = ()
        self._healthy = False

    @property
    def healthy(self) -> bool:
        return self._healthy

    @property
    def grants(self) -> tuple[Grant, ...]:
        if not self._healthy:
            raise StorageUnavailable("Storage is unavailable")
        return self._grants

    def close(self) -> None:
        """Invalidate access when runtime unloads."""
        self._healthy = False

    async def async_initialize(self) -> None:
        """Only a new config flow may initialize a new random storage key."""
        async with self._lock:
            try:
                # Check before native Store can rename a corrupt existing file.
                if await self._hass.async_add_executor_job(
                    Path(self._store.path).exists
                ):
                    raise StorageUnavailable("Storage already exists")
                if await self._store.async_load() is not None:
                    raise StorageUnavailable("Storage already exists")
                await self._save(())
            except (Exception, asyncio.CancelledError) as err:
                self._healthy = False
                if isinstance(err, asyncio.CancelledError):
                    raise
                raise StorageUnavailable("Storage initialization failed") from None
            self._grants = ()
            self._healthy = True

    async def async_load(self) -> None:
        async with self._lock:
            self._healthy = False
            try:
                envelope = await self._hass.async_add_executor_job(self._read_envelope)
                data = require_keys(
                    await self._store.async_load(), {"revision", "grants"}
                )
                if data != envelope["data"]:
                    raise StorageUnavailable("Storage cache differs from disk")
                require_text(data["revision"])
                if type(data["grants"]) is not list or len(data["grants"]) > MAX_GRANTS:
                    raise ValidationError("Invalid stored grant collection")
                grants = tuple(Grant.from_dict(item) for item in data["grants"])
                if len({grant.grant_id for grant in grants}) != len(grants):
                    raise ValidationError("Duplicate grants")
            except Exception:
                raise StorageUnavailable("Storage load failed") from None
            self._grants = grants
            self._healthy = True

    async def async_add(self, grant: Grant) -> None:
        """Persist an immutable grant after the application service admits it."""
        if type(grant) is not Grant:
            raise ValidationError("Invalid grant")
        async with self._lock:
            current = self.grants
            if len(current) >= MAX_GRANTS or any(
                g.grant_id == grant.grant_id for g in current
            ):
                raise ValidationError("Grant capacity or duplicate ID")
            await self._commit((*current, grant))

    async def async_revoke(self, grant_id: str, *, actor: str, now: datetime) -> Grant:
        """Internal persistence operation; callers must authenticate owners."""
        require_text(actor)
        now = require_time(now)
        async with self._lock:
            current = self.grants
            grant = next((g for g in current if g.grant_id == grant_id), None)
            if grant is None:
                raise ValidationError("Unknown grant")
            if grant.revoked_at is not None:
                return grant
            revoked = replace(grant, revoked_at=now, revoked_by=actor)
            await self._commit(tuple(revoked if g is grant else g for g in current))
            return revoked

    async def _commit(self, grants: tuple[Grant, ...]) -> None:
        try:
            await self._save(grants)
        except (Exception, asyncio.CancelledError) as err:
            self._healthy = False
            if isinstance(err, asyncio.CancelledError):
                raise
            raise StorageUnavailable("Storage save failed") from None
        self._grants = grants

    async def _save(self, grants: tuple[Grant, ...]) -> None:
        if self._hass.state in (
            CoreState.stopping,
            CoreState.final_write,
            CoreState.stopped,
        ):
            raise StorageUnavailable("Home Assistant is stopping")
        data = {"revision": str(uuid4()), "grants": [g.to_dict() for g in grants]}
        await self._store.async_save(data)
        # Disk read bypasses Store caches and detects swallowed/deferred writes.
        await self._hass.async_add_executor_job(self._verify_saved, data)

    def _read_envelope(self) -> dict:
        with Path(self._store.path).open("rb") as handle:
            raw = handle.read(2_000_001)
        if len(raw) > 2_000_000:
            raise StorageUnavailable("Storage exceeds size limit")
        envelope = require_keys(
            json.loads(raw), {"version", "minor_version", "key", "data"}
        )
        if (
            type(envelope["version"]) is not int
            or envelope["version"] != STORAGE_VERSION
            or type(envelope["minor_version"]) is not int
            or envelope["minor_version"] != 1
            or envelope["key"] != self._store.key
        ):
            raise StorageUnavailable("Unsupported storage envelope")
        return envelope

    def _verify_saved(self, expected: dict) -> None:
        if self._read_envelope()["data"] != expected:
            raise StorageUnavailable("Storage write could not be verified")
