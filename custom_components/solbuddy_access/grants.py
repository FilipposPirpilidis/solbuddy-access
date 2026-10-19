"""Owner administration and serialized internal execution boundary.

The guest HTTP boundary supplies a live-session guard; internal tests may call
the execution engine directly with a synthetic grant binding.
"""

import asyncio
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import datetime
from time import monotonic

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .audit import AuditStore
from .executor import LightExecutor
from .models import Grant, ValidationError, parse_time, require_text
from .permissions import Decision, evaluate
from .storage import GrantStorage, StorageUnavailable


class AccessDenied(PermissionError):
    """A security check failed; no untrusted input appears in error text."""


class GrantManager:
    def __init__(
        self,
        hass: HomeAssistant,
        storage: GrantStorage,
        audit: AuditStore,
        executor: LightExecutor,
    ) -> None:
        self.hass = hass
        self.storage = storage
        self.audit = audit
        self.executor = executor
        self.active = True
        self._locks = {g.grant_id: asyncio.Lock() for g in storage.grants}
        self._waiting: dict[str, int] = {}
        self._revoking: set[str] = set()
        self._create_lock = asyncio.Lock()
        self._wall = dt_util.utcnow()
        self._mono = monotonic()
        self._clock_healthy = True
        self.execution_timeout = 10.0
        self.on_revoke: Callable[[str], None] = lambda grant_id: None
        self.on_close: Callable[[], None] = lambda: None

    def now(self) -> datetime:
        wall, mono = dt_util.utcnow(), monotonic()
        if abs((wall - self._wall).total_seconds() - (mono - self._mono)) > 5:
            self._clock_healthy = False
        self._wall, self._mono = wall, mono
        if not self._clock_healthy:
            raise AccessDenied("clock_untrusted")
        return wall

    async def require_owner(self, user_id: str) -> None:
        if not self.active:
            raise AccessDenied("integration_unavailable")
        user = await self.hass.auth.async_get_user(user_id)
        if (
            user is None
            or not user.is_active
            or not user.is_owner
            or user.system_generated
        ):
            raise AccessDenied("owner_required")

    def get(self, grant_id: str) -> Grant:
        if not self.active:
            raise AccessDenied("integration_unavailable")
        require_text(grant_id)
        grant = next((g for g in self.storage.grants if g.grant_id == grant_id), None)
        if grant is None:
            raise ValidationError("Unknown grant")
        return grant

    @asynccontextmanager
    async def _gate(self, grant_id: str, *, revocation: bool = False):
        self.get(grant_id)
        if not revocation and self._waiting.get(grant_id, 0) >= 8:
            raise AccessDenied("queue_full")
        self._waiting[grant_id] = self._waiting.get(grant_id, 0) + 1
        acquired = False
        try:
            async with asyncio.timeout(15):
                await self._locks[grant_id].acquire()
            acquired = True
            if not self.active:
                raise AccessDenied("integration_unavailable")
            yield
        finally:
            self._waiting[grant_id] -= 1
            if acquired:
                self._locks[grant_id].release()

    async def create(self, owner_id: str, data: dict) -> Grant:
        await self.require_owner(owner_id)
        if set(data) - {
            "guest_display_name",
            "guest_identifier",
            "starts_at",
            "expires_at",
            "policies",
        }:
            raise ValidationError("Invalid grant fields")
        if not {"guest_display_name", "starts_at", "expires_at", "policies"} <= set(
            data
        ):
            raise ValidationError("Missing grant fields")
        # The first milestone deliberately grants exactly one reviewed light.
        if type(data["policies"]) is not list or len(data["policies"]) != 1:
            raise ValidationError("Exactly one light is required")
        async with self._create_lock:
            policy = self.executor.enroll(data["policies"][0])
            grant = Grant.create(
                guest_display_name=data["guest_display_name"],
                guest_identifier=data.get("guest_identifier"),
                created_by=owner_id,
                now=self.now(),
                starts_at=parse_time(data["starts_at"]),
                expires_at=parse_time(data["expires_at"]),
                policies=(policy,),
            )
            await self.audit.append("create_requested", grant.grant_id, self.now())
            await self.require_owner(owner_id)
            # Revalidate enrollment after awaited audit IO.
            if self.executor.enroll(data["policies"][0]) != policy:
                raise AccessDenied("entity_changed")
            if self.now() >= grant.expires_at:
                raise AccessDenied("grant_expired")
            await self.storage.async_add(grant)
            self._locks[grant.grant_id] = asyncio.Lock()
            return grant

    async def revoke(self, owner_id: str, grant_id: str) -> dict:
        await self.require_owner(owner_id)
        self.get(grant_id)
        # Stops queued execution even before the durable revoke obtains its gate.
        self._revoking.add(grant_id)
        self.on_revoke(grant_id)
        async with self._gate(grant_id, revocation=True):
            await self.require_owner(owner_id)
            # Revocation must remain available when clock/audit health is lost.
            existing = self.get(grant_id)
            now = max(dt_util.utcnow(), existing.created_at)
            grant = await self.storage.async_revoke(grant_id, actor=owner_id, now=now)
            try:
                await self.audit.append("revoked", grant_id, now)
            except StorageUnavailable:
                pass
            return {
                "grant": self.describe(grant),
                "audit_degraded": not self.audit.healthy,
            }

    def describe(self, grant: Grant) -> dict:
        return grant.to_dict() | {"status": grant.status(dt_util.utcnow()).value}

    def check(self, grant_id: str, request: dict) -> Decision:
        grant = self.get(grant_id)
        if set(request) != {"entity_id", "action", "parameters"}:
            raise ValidationError("Invalid action fields")
        if grant_id in self._revoking:
            return Decision(False, "grant_revoked")
        if not self.audit.healthy:
            return Decision(False, "audit_unavailable")
        if any(p.device_id is None or p.unique_id is None for p in grant.policies):
            return Decision(False, "legacy_binding")
        entity_id = request["entity_id"]
        evidence = self.executor.snapshot(entity_id) if type(entity_id) is str else None
        return evaluate(
            grant,
            now=self.now(),
            entity=evidence,
            storage_healthy=self.storage.healthy,
            **request,
        )

    async def execute(
        self,
        grant_id: str,
        request: dict,
        *,
        authorize: Callable[[], None] | None = None,
    ) -> dict:
        """Internal dispatch; guest transport must supply its live-session guard."""
        # Copy primitive request data so a caller cannot mutate it across awaits.
        if type(request) is not dict or set(request) != {
            "entity_id",
            "action",
            "parameters",
        }:
            raise ValidationError("Invalid action fields")
        if type(request["parameters"]) is not dict:
            raise ValidationError("Invalid parameters")
        request = request | {"parameters": dict(request["parameters"])}
        async with self._gate(grant_id):
            if authorize is not None:
                authorize()
            decision = self.check(grant_id, request)
            if not decision.allowed:
                await self.audit.append("denied", grant_id, dt_util.utcnow())
                return {"outcome": "denied", "reason": decision.reason}
            operation_id = await self.audit.append(
                "admitted", grant_id, self.now(), action=request["action"]
            )
            # Nothing may await between these fresh checks and executor invocation.
            if authorize is not None:
                authorize()
            decision = self.check(grant_id, request)
            if not decision.allowed:
                await self.audit.append(
                    "denied",
                    grant_id,
                    dt_util.utcnow(),
                    action=request["action"],
                    operation_id=operation_id,
                )
                return {"outcome": "denied", "reason": decision.reason}
            policy = next(
                p
                for p in self.get(grant_id).policies
                if p.entity_id == request["entity_id"]
            )
            outcome = "dispatched"
            try:
                async with asyncio.timeout(self.execution_timeout):
                    await self.executor.dispatch(
                        policy, request["action"], request["parameters"]
                    )
            except asyncio.CancelledError:
                # Persisted admission with no completion is explicitly unknown.
                raise
            except Exception:
                # No automatic retry: timeout/error can occur after hardware dispatch.
                outcome = "unknown"
            try:
                await self.audit.append(
                    outcome,
                    grant_id,
                    dt_util.utcnow(),
                    action=request["action"],
                    operation_id=operation_id,
                )
            except StorageUnavailable:
                outcome = "unknown"
            return {"outcome": outcome}

    async def close(self) -> None:
        """Block new work, then drain each bounded admitted command before unload."""
        self.active = False
        self.on_close()
        async with self._create_lock:
            pass
        for lock in self._locks.values():
            async with lock:
                pass
        self.storage.close()
