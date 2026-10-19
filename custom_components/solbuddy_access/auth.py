"""Volatile scoped credentials; no HA tokens, secrets on disk, or raw logging."""

import hashlib
import hmac
import re
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from time import monotonic
from typing import TYPE_CHECKING

from .models import GrantStatus
from .storage import StorageUnavailable

if TYPE_CHECKING:
    from .grants import GrantManager


class GuestAccessDisabled(PermissionError):
    """Guest access is not enabled for this runtime."""


class AuthError(PermissionError):
    """A safe HTTP status/code, never containing credential or request data."""

    def __init__(self, status: int = 401, code: str = "unauthorized") -> None:
        super().__init__(code)
        self.status = status
        self.code = code


@dataclass(slots=True)
class Bucket:
    capacity: float
    per_second: float
    tokens: float = field(init=False)
    updated: float = field(default_factory=monotonic)

    def __post_init__(self) -> None:
        self.tokens = self.capacity

    def take(self) -> None:
        now = monotonic()
        self.tokens = min(
            self.capacity, self.tokens + max(0, now - self.updated) * self.per_second
        )
        self.updated = now
        if self.tokens < 1:
            raise AuthError(429, "rate_limited")
        self.tokens -= 1


@dataclass(slots=True, repr=False)
class Credential:
    digest: bytes
    grant_id: str
    expires_at: datetime
    deadline: float
    sequence: int = 1
    busy: bool = False
    limiter: Bucket = field(default_factory=lambda: Bucket(5, 0.5))


def _digest(token: object, prefix: str) -> bytes:
    if (
        type(token) is not str
        or re.fullmatch(re.escape(prefix) + r"[A-Za-z0-9_-]{43}", token) is None
    ):
        raise AuthError()
    return hashlib.sha256(token.encode("ascii")).digest()


class GuestAuthenticator:
    """One invitation and session per grant, at most the 100 stored grants."""

    def __init__(
        self, manager: GrantManager | None = None, *, enabled: bool = False
    ) -> None:
        self.manager = manager
        self.enabled = enabled
        self._invitations: dict[str, Credential] = {}
        self._sessions: dict[str, Credential] = {}
        self._global = Bucket(60, 2)
        self._sources: dict[str, Bucket] = {}
        if manager is not None:
            manager.on_revoke = self.invalidate
            manager.on_close = self.close

    async def authenticate(self, credential: object = None) -> None:
        """No standalone bearer-to-principal shortcut bypasses request sequences."""
        raise GuestAccessDisabled("Use the authenticated request boundary")

    def close(self) -> None:
        self.enabled = False
        self._invitations.clear()
        self._sessions.clear()
        self._sources.clear()

    def invalidate(self, grant_id: str) -> None:
        self._invitations.pop(grant_id, None)
        self._sessions.pop(grant_id, None)

    def limit_source(self, peer: str) -> None:
        """Use actual socket peers, never forwarded IP headers; bounded map."""
        self._global.take()
        now = monotonic()
        self._sources = {
            k: v for k, v in self._sources.items() if now - v.updated < 300
        }
        if peer not in self._sources:
            if len(self._sources) >= 256:
                raise AuthError(429, "rate_limited")
            self._sources[peer] = Bucket(20, 1 / 3)
        self._sources[peer].take()

    def _active(self, grant_id: str):
        if not self.enabled or self.manager is None or not self.manager.active:
            raise AuthError()
        manager = self.manager
        if not manager.storage.healthy or not manager.audit.healthy:
            raise StorageUnavailable("Security state unavailable")
        try:
            grant = manager.get(grant_id)
            now = manager.now()
        except PermissionError:
            raise StorageUnavailable("Security clock unavailable") from None
        if grant_id in manager._revoking or grant.status(now) is not GrantStatus.ACTIVE:
            self.invalidate(grant_id)
            raise AuthError()
        if any(p.device_id is None or p.unique_id is None for p in grant.policies):
            raise AuthError()
        return grant, now

    def _lookup(
        self, token: object, prefix: str, records: dict[str, Credential]
    ) -> Credential:
        if not self.enabled:
            raise AuthError()
        digest = _digest(token, prefix)
        found = None
        for item in records.values():
            if hmac.compare_digest(digest, item.digest):
                found = item
        if found is None:
            raise AuthError()
        self.assert_live(found, records)
        return found

    def assert_live(
        self, item: Credential, records: dict[str, Credential] | None = None
    ) -> None:
        records = self._sessions if records is None else records
        if records.get(item.grant_id) is not item:
            raise AuthError()
        _, now = self._active(item.grant_id)
        if now >= item.expires_at or monotonic() >= item.deadline:
            records.pop(item.grant_id, None)
            raise AuthError()

    def _new(self, grant_id: str, prefix: str, seconds: int) -> tuple[str, Credential]:
        grant, now = self._active(grant_id)
        expires = min(now + timedelta(seconds=seconds), grant.expires_at)
        token = prefix + secrets.token_urlsafe(32)
        item = Credential(
            _digest(token, prefix),
            grant_id,
            expires,
            monotonic() + (expires - now).total_seconds(),
        )
        return token, item

    async def issue(self, owner_id: str, grant_id: str) -> dict:
        if not self.enabled or self.manager is None:
            raise GuestAccessDisabled("Guest access is disabled")
        await self.manager.require_owner(owner_id)
        async with self.manager._gate(grant_id):
            await self.manager.require_owner(owner_id)
            _, now = self._active(grant_id)
            self.invalidate(grant_id)
            await self.manager.audit.append("invitation_issued", grant_id, now)
            await self.manager.require_owner(owner_id)
            token, item = self._new(grant_id, "sbai_", 300)
            self._invitations[grant_id] = item
            return {"invitation": token, "expires_at": item.expires_at.isoformat()}

    async def exchange(self, token: object) -> dict:
        item = self._lookup(token, "sbai_", self._invitations)
        async with self.manager._gate(item.grant_id):
            self.assert_live(item, self._invitations)
            self._invitations.pop(item.grant_id)  # Consume before any awaited IO.
            await self.manager.audit.append(
                "session_issued", item.grant_id, self.manager.now()
            )
            # Deadline can pass while awaiting audit IO, even though grant is active.
            if self.manager.now() >= item.expires_at or monotonic() >= item.deadline:
                raise AuthError()
            token, session = self._new(item.grant_id, "sbas_", 900)
            self._sessions[item.grant_id] = session
            return self._response(token, session)

    @asynccontextmanager
    async def request(
        self, token: object, sequence: object
    ) -> AsyncIterator[Credential]:
        item = self._lookup(token, "sbas_", self._sessions)
        if type(sequence) is not int or not 1 <= sequence <= 2**31 - 1:
            raise AuthError(409, "sequence_conflict")
        if item.busy or sequence != item.sequence:
            raise AuthError(409, "sequence_conflict")
        item.limiter.take()
        item.busy = True
        item.sequence += 1
        try:
            yield item
        finally:
            item.busy = False

    async def renew(self, item: Credential) -> dict:
        async with self.manager._gate(item.grant_id):
            self.assert_live(item)
            await self.manager.audit.append(
                "session_rotated", item.grant_id, self.manager.now()
            )
            self.assert_live(item)
            token, replacement = self._new(item.grant_id, "sbas_", 900)
            # Rotation must not reset the request throttle.
            replacement.limiter = item.limiter
            self._sessions[item.grant_id] = replacement
            return self._response(token, replacement)

    @staticmethod
    def _response(token: str, item: Credential) -> dict:
        return {
            "session_token": token,
            "expires_at": item.expires_at.isoformat(),
            "next_sequence": 1,
        }
