"""Bounded redacted audit storage, independent of revocation persistence."""

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from homeassistant.core import CoreState, HomeAssistant
from homeassistant.helpers.storage import Store

from .models import parse_time, require_keys
from .storage import StorageUnavailable

EVENTS = frozenset(
    {"create_requested", "revoked", "denied", "admitted", "dispatched", "unknown"}
)
MAX_RECORDS = 10_000


class AuditStore:
    def __init__(self, hass: HomeAssistant, storage_id: str) -> None:
        self.hass = hass
        self.store = Store[dict](
            hass,
            1,
            f"solbuddy_access.{storage_id}.audit",
            private=True,
            atomic_writes=True,
        )
        self.healthy = False
        self._records: list[dict] = []
        self._lock = asyncio.Lock()

    def _read(self) -> dict:
        with Path(self.store.path).open("rb") as handle:
            raw = handle.read(4_000_001)
        if len(raw) > 4_000_000:
            raise StorageUnavailable("Audit size exceeded")
        envelope = require_keys(
            json.loads(raw), {"version", "minor_version", "key", "data"}
        )
        if (
            type(envelope["version"]) is not int
            or envelope["version"] != 1
            or type(envelope["minor_version"]) is not int
            or envelope["minor_version"] != 1
            or envelope["key"] != self.store.key
        ):
            raise StorageUnavailable("Unsupported audit version")
        data = require_keys(envelope["data"], {"revision", "records"})
        UUID(data["revision"])
        records = data["records"]
        if type(records) is not list or len(records) > MAX_RECORDS:
            raise StorageUnavailable("Invalid audit records")
        for record in records:
            require_keys(
                record,
                {"event_id", "operation_id", "time", "grant_id", "event", "action"},
            )
            UUID(record["event_id"])
            UUID(record["operation_id"])
            UUID(record["grant_id"])
            parse_time(record["time"])
            if record["event"] not in EVENTS:
                raise StorageUnavailable("Invalid audit event")
            if record["action"] not in (None, "turn_on", "turn_off", "set_brightness"):
                raise StorageUnavailable("Invalid audit action")
        return data

    async def load(self, *, initialize: bool) -> None:
        """Missing audit can be initialized only for a pre-Phase-2 config entry."""
        try:
            exists = await self.hass.async_add_executor_job(
                Path(self.store.path).exists
            )
            if not exists and initialize:
                await self._save([])
            data = await self.hass.async_add_executor_job(self._read)
            self._records = data["records"]
        except Exception:
            self.healthy = False
            raise StorageUnavailable("Audit unavailable") from None
        self.healthy = True

    async def append(
        self,
        event: str,
        grant_id: str,
        now: datetime,
        *,
        action: str | None = None,
        operation_id: str | None = None,
    ) -> str:
        if event not in EVENTS:
            raise ValueError("Unknown audit event")
        UUID(grant_id)
        operation_id = operation_id or str(uuid4())
        UUID(operation_id)
        if action not in ("turn_on", "turn_off", "set_brightness"):
            action = None
        async with self._lock:
            if not self.healthy:
                raise StorageUnavailable("Audit unavailable")
            threshold = now - timedelta(days=7)
            records = [r for r in self._records if parse_time(r["time"]) >= threshold]
            records = records[-(MAX_RECORDS - 1) :]
            records.append(
                {
                    "event_id": str(uuid4()),
                    "time": now.isoformat(),
                    "grant_id": grant_id,
                    "event": event,
                    "action": action,
                    "operation_id": operation_id,
                }
            )
            try:
                await self._save(records)
            except (Exception, asyncio.CancelledError) as err:
                self.healthy = False
                if isinstance(err, asyncio.CancelledError):
                    raise
                raise StorageUnavailable("Audit save failed") from None
            self._records = records
            return operation_id

    async def _save(self, records: list[dict]) -> None:
        if self.hass.state in {
            CoreState.stopping,
            CoreState.final_write,
            CoreState.stopped,
        }:
            raise StorageUnavailable("Home Assistant stopping")
        data = {"revision": str(uuid4()), "records": records}
        await self.store.async_save(data)
        if await self.hass.async_add_executor_job(self._read) != data:
            raise StorageUnavailable("Audit save not verified")
