"""Session lifecycle, replay races, expiry and final-dispatch revalidation."""

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.solbuddy_access.auth import AuthError, GuestAuthenticator
from custom_components.solbuddy_access.storage import StorageUnavailable
from tests.test_phase2 import calls as calls
from tests.test_phase2 import created as created
from tests.test_phase2 import hardware as hardware
from tests.test_phase2 import manager as manager
from tests.test_phase2 import payload as payload


@pytest.fixture
async def auth(manager, created):
    return GuestAuthenticator(manager, enabled=True)


@pytest.fixture
async def invitation(auth, created, hass_owner_user):
    return await auth.issue(hass_owner_user.id, created.grant_id)


@pytest.fixture
async def session(auth, invitation):
    return await auth.exchange(invitation["invitation"])


async def test_exchange_single_use_and_digests(
    auth, invitation, session, manager, hass
):
    with pytest.raises(AuthError):
        await auth.exchange(invitation["invitation"])
    token = session["session_token"]
    item = next(iter(auth._sessions.values()))
    assert len(item.digest) == 32
    assert token not in repr(item)
    assert token not in str(auth.__dict__)
    audit = await hass.async_add_executor_job(manager.audit._read)
    assert token not in str(audit) and invitation["invitation"] not in str(audit)
    assert not auth._invitations


async def test_exchange_race(auth, invitation):
    results = await asyncio.gather(
        auth.exchange(invitation["invitation"]),
        auth.exchange(invitation["invitation"]),
        return_exceptions=True,
    )
    assert sum(isinstance(result, dict) for result in results) == 1
    assert sum(isinstance(result, AuthError) for result in results) == 1


async def test_replay_busy_and_rotation(auth, session):
    token = session["session_token"]
    async with auth.request(token, 1) as item:
        with pytest.raises(AuthError) as error:
            async with auth.request(token, 1):
                pytest.fail("Replay admitted")
        assert error.value.status == 409
        with pytest.raises(AuthError):
            async with auth.request(token, 2):
                pytest.fail("Concurrent request admitted")
        rotated = await auth.renew(item)
    with pytest.raises(AuthError):
        async with auth.request(token, 2):
            pytest.fail("Old token admitted")
    async with auth.request(rotated["session_token"], 1):
        pass


@pytest.mark.parametrize("sequence", [0, True, -1, "1", 2, 2**31])
async def test_invalid_sequences(auth, session, sequence):
    with pytest.raises(AuthError) as error:
        async with auth.request(session["session_token"], sequence):
            pytest.fail("Invalid sequence admitted")
    assert error.value.status == 409


async def test_expired_session_wall_and_monotonic(auth, session, manager):
    item = next(iter(auth._sessions.values()))
    with patch.object(manager, "now", return_value=item.expires_at):
        with pytest.raises(AuthError):
            async with auth.request(session["session_token"], 1):
                pytest.fail("Expired token admitted")


async def test_monotonic_expiry(auth, session):
    item = next(iter(auth._sessions.values()))
    item.deadline = 0
    with pytest.raises(AuthError):
        async with auth.request(session["session_token"], 1):
            pytest.fail("Expired deadline admitted")


async def test_invitation_expiry(auth, invitation):
    next(iter(auth._invitations.values())).deadline = 0
    with pytest.raises(AuthError):
        await auth.exchange(invitation["invitation"])


async def test_replacement_invalidates_prior_session(
    auth, session, created, hass_owner_user
):
    invite = await auth.issue(hass_owner_user.id, created.grant_id)
    with pytest.raises(AuthError):
        async with auth.request(session["session_token"], 1):
            pytest.fail("Replaced session admitted")
    assert (await auth.exchange(invite["invitation"]))["session_token"] != session[
        "session_token"
    ]


async def test_revocation_invalidates_credentials(
    auth, session, manager, created, hass_owner_user
):
    await manager.revoke(hass_owner_user.id, created.grant_id)
    assert not auth._sessions and not auth._invitations
    with pytest.raises(AuthError):
        async with auth.request(session["session_token"], 1):
            pytest.fail("Revoked session admitted")


async def test_failed_revoke_invalidates_credentials(
    auth, session, manager, created, hass_owner_user
):
    with patch.object(manager.storage._store, "async_save", new=AsyncMock()):
        with pytest.raises(StorageUnavailable):
            await manager.revoke(hass_owner_user.id, created.grant_id)
    assert not auth._sessions


async def test_restart_and_unload_invalidate(auth, session, manager):
    restarted = GuestAuthenticator(manager, enabled=True)
    with pytest.raises(AuthError):
        async with restarted.request(session["session_token"], 1):
            pytest.fail("Restart retained token")
    # Reconnect lifecycle callback to original auth before testing unload.
    manager.on_close = auth.close
    await manager.close()
    assert not auth.enabled and not auth._sessions


async def test_expiry_during_audit_never_dispatches(auth, session, manager, calls):
    original = manager.audit.append
    item = next(iter(auth._sessions.values()))

    async def expire(event, *args, **kwargs):
        result = await original(event, *args, **kwargs)
        if event == "admitted":
            item.deadline = 0
        return result

    async with auth.request(session["session_token"], 1) as ticket:
        with (
            patch.object(manager.audit, "append", side_effect=expire),
            pytest.raises(AuthError),
        ):
            await manager.execute(
                ticket.grant_id,
                {
                    "entity_id": "light.guest_room",
                    "action": "turn_on",
                    "parameters": {},
                },
                authorize=lambda: auth.assert_live(ticket),
            )
    assert calls == []


async def test_exchange_audit_fault_consumes_invitation(auth, invitation, manager):
    with patch.object(manager.audit.store, "async_save", new=AsyncMock()):
        with pytest.raises(StorageUnavailable):
            await auth.exchange(invitation["invitation"])
    assert not auth._invitations and not auth._sessions


async def test_rotation_does_not_reset_rate_budget(auth, session):
    token = session["session_token"]
    for _ in range(5):
        async with auth.request(token, 1) as item:
            rotated = await auth.renew(item)
        token = rotated["session_token"]
    with pytest.raises(AuthError) as error:
        async with auth.request(token, 1):
            pytest.fail("Rotation bypassed throttle")
    assert error.value.status == 429


async def test_bounded_source_limiter(auth):
    for index in range(256):
        auth._global.tokens = 60
        auth.limit_source(str(index))
    auth._global.tokens = 60
    with pytest.raises(AuthError):
        auth.limit_source("overflow")
    assert len(auth._sources) == 256


async def test_session_capped_at_grant_expiry(auth, created, hass_owner_user, manager):
    with patch.object(
        manager, "now", return_value=created.expires_at - timedelta(seconds=20)
    ):
        invite = await auth.issue(hass_owner_user.id, created.grant_id)
        result = await auth.exchange(invite["invitation"])
        assert result["expires_at"] == created.expires_at.isoformat()


async def test_nonowner_cannot_issue(auth, created, hass_admin_user):
    with pytest.raises(PermissionError):
        await auth.issue(hass_admin_user.id, created.grant_id)


async def test_revoke_during_exchange_audit(
    auth, invitation, manager, created, hass_owner_user
):
    entered, release = asyncio.Event(), asyncio.Event()
    original = manager.audit.append

    async def pause(event, *args, **kwargs):
        result = await original(event, *args, **kwargs)
        if event == "session_issued":
            entered.set()
            await release.wait()
        return result

    with patch.object(manager.audit, "append", side_effect=pause):
        exchange = asyncio.create_task(auth.exchange(invitation["invitation"]))
        await entered.wait()
        revoke = asyncio.create_task(
            manager.revoke(hass_owner_user.id, created.grant_id)
        )
        # Run owner validation and revocation marking before audit resumes.
        await asyncio.sleep(0)
        assert created.grant_id in manager._revoking
        release.set()
        with pytest.raises(AuthError):
            await exchange
        await revoke
    assert not auth._sessions


async def test_renewal_expiry_during_audit(auth, session, manager):
    original = manager.audit.append
    async with auth.request(session["session_token"], 1) as item:

        async def expire(event, *args, **kwargs):
            result = await original(event, *args, **kwargs)
            item.deadline = 0
            return result

        with (
            patch.object(manager.audit, "append", side_effect=expire),
            pytest.raises(AuthError),
        ):
            await auth.renew(item)
    assert not auth._sessions
