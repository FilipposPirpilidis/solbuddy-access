"""Real Ed25519 proofs, fixed SBUD valuation, transport and bypass regressions."""

import asyncio
import base64
from datetime import UTC, datetime
from decimal import Decimal
from time import monotonic
from unittest.mock import AsyncMock, patch

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from custom_components.solbuddy_access.auth import AuthError, GuestAuthenticator
from custom_components.solbuddy_access.const import DOMAIN
from custom_components.solbuddy_access.eligibility import (
    Eligibility,
    Evidence,
    balance,
    validate_mint,
)
from custom_components.solbuddy_access.guest_api import BASE
from custom_components.solbuddy_access.models import Grant, ValidationError
from custom_components.solbuddy_access.wallet_identity import (
    MAINNET_GENESIS,
    MINT,
    TOKEN_PROGRAM,
    encode_key,
)
from tests.test_guest_api import created as created
from tests.test_guest_api import owner_token as owner_token
from tests.test_guest_api import tls_client as tls_client
from tests.test_guest_api import tls_contexts as tls_contexts
from tests.test_phase2 import calls as calls
from tests.test_phase2 import hardware as hardware
from tests.test_phase2 import manager as manager
from tests.test_phase2 import payload as payload

ORIGIN = "https://ha.example"


@pytest.fixture
def key():
    return Ed25519PrivateKey.generate()


def address(key):
    return encode_key(key.public_key().public_bytes_raw())


def sign(key, challenge):
    return base64.b64encode(key.sign(challenge["message"].encode())).decode()


@pytest.fixture
async def wallet_setup(manager, payload, hass_owner_user, key):
    service = AsyncMock()
    service.verify.side_effect = lambda wallet, now: Evidence(
        wallet, int(now().timestamp()), int(now().timestamp()), monotonic() + 30
    )
    auth = GuestAuthenticator(
        manager,
        enabled=True,
        wallet_enabled=True,
        eligibility=service,
        installation_id="installation-a",
    )
    grant = await manager.create(
        hass_owner_user.id, payload | {"wallet_address": address(key)}
    )
    invitation = await auth.issue(hass_owner_user.id, grant.grant_id)
    item = auth._lookup(invitation["invitation"], "sbai_", auth._invitations)
    return auth, grant, invitation, item, service


async def test_wallet_roundtrip_and_no_bypass(wallet_setup, key, manager, calls):
    auth, grant, invitation, item, service = wallet_setup
    with pytest.raises(AuthError, match="wallet_proof_required"):
        await auth.exchange(invitation["invitation"])
    challenge = auth.challenge(item, ORIGIN, renewal=False)
    assert address(key) in challenge["message"] and MINT in challenge["message"]
    result = await auth.wallet_verify(item, ORIGIN, sign(key, challenge), renewal=False)
    assert not auth._invitations
    async with auth.request(result["session_token"], 1) as session:
        with pytest.raises(AuthError, match="wallet_proof_required"):
            await auth.renew(session)
        assert (
            await manager.execute(
                grant.grant_id,
                {
                    "entity_id": "light.guest_room",
                    "action": "turn_on",
                    "parameters": {},
                },
                authorize=lambda: auth.assert_live(session),
            )
        )["outcome"] == "dispatched"
    assert len(calls) == 1
    async with auth.request(result["session_token"], 2) as session:
        challenge = auth.challenge(session, ORIGIN, renewal=True)
    async with auth.request(result["session_token"], 3) as session:
        renewed = await auth.wallet_verify(
            session, ORIGIN, sign(key, challenge), renewal=True
        )
    assert renewed["session_token"] != result["session_token"]
    assert service.verify.await_count == 2
    with pytest.raises(AuthError):
        async with auth.request(result["session_token"], 4):
            pytest.fail("Old session accepted")


@pytest.mark.parametrize(
    "failure",
    ["wrong_key", "wrong_origin", "expired", "purpose", "signature", "changed_message"],
)
async def test_invalid_wallet_proof(wallet_setup, key, failure):
    auth, grant, invite, item, service = wallet_setup
    challenge = auth.challenge(item, ORIGIN, renewal=False)
    signature = sign(key, challenge)
    origin, renewal = ORIGIN, False
    if failure == "wrong_key":
        signature = sign(Ed25519PrivateKey.generate(), challenge)
    if failure == "wrong_origin":
        origin = "https://evil.example"
    if failure == "expired":
        auth._challenges[grant.grant_id].deadline = 0
    if failure == "purpose":
        auth._challenges[grant.grant_id].renewal = True
    if failure == "signature":
        signature = "bad"
    if failure == "changed_message":
        signature = sign(key, {"message": challenge["message"] + "changed"})
    with pytest.raises(AuthError):
        await auth.wallet_verify(item, origin, signature, renewal=renewal)
    service.verify.assert_not_awaited()
    assert not auth._sessions


async def test_proof_replay_race(wallet_setup, key):
    auth, grant, invite, item, service = wallet_setup
    proof = sign(key, auth.challenge(item, ORIGIN, renewal=False))
    results = await asyncio.gather(
        auth.wallet_verify(item, ORIGIN, proof, renewal=False),
        auth.wallet_verify(item, ORIGIN, proof, renewal=False),
        return_exceptions=True,
    )
    assert sum(isinstance(r, dict) for r in results) == 1
    assert sum(isinstance(r, AuthError) for r in results) == 1


async def test_revoke_during_provider_io(wallet_setup, key, manager, hass_owner_user):
    auth, grant, invite, item, service = wallet_setup
    entered, release = asyncio.Event(), asyncio.Event()

    async def provider(wallet, now):
        entered.set()
        await release.wait()
        return Evidence(
            wallet, int(now().timestamp()), int(now().timestamp()), monotonic() + 30
        )

    service.verify.side_effect = provider
    proof = sign(key, auth.challenge(item, ORIGIN, renewal=False))
    task = asyncio.create_task(auth.wallet_verify(item, ORIGIN, proof, renewal=False))
    await entered.wait()
    await manager.revoke(hass_owner_user.id, grant.grant_id)
    release.set()
    with pytest.raises(AuthError):
        await task
    assert not auth._sessions and not auth._challenges


async def test_evidence_expires_during_audit(wallet_setup, key, manager):
    auth, grant, invite, item, service = wallet_setup
    evidence = Evidence(
        address(key),
        int(manager.now().timestamp()),
        int(manager.now().timestamp()),
        monotonic() + 30,
    )
    service.verify.side_effect = None
    service.verify.return_value = evidence
    original = manager.audit.append

    async def expire(*args, **kwargs):
        result = await original(*args, **kwargs)
        object.__setattr__(evidence, "deadline", 0)
        return result

    proof = sign(key, auth.challenge(item, ORIGIN, renewal=False))
    with (
        patch.object(manager.audit, "append", side_effect=expire),
        pytest.raises(AuthError),
    ):
        await auth.wallet_verify(item, ORIGIN, proof, renewal=False)
    assert not auth._sessions


async def test_wallet_disabled_and_persistence(wallet_setup, key, manager, hass):
    from custom_components.solbuddy_access.storage import GrantStorage

    auth, grant, invite, item, service = wallet_setup
    stored = grant.to_dict()
    assert stored["schema_version"] == 3
    assert Grant.from_dict(stored) == grant
    stored["wallet_policy"] = "other"
    with pytest.raises(ValidationError):
        Grant.from_dict(stored)
    reloaded = GrantStorage(hass, manager.storage._store.key.split(".")[1])
    await reloaded.async_load()
    assert reloaded.grants[0].wallet_address == address(key)
    auth.wallet_enabled = False
    with pytest.raises(AuthError):
        auth.challenge(item, ORIGIN, renewal=False)
    auth.close()
    assert not auth._challenges


def mint_record():
    return {
        "owner": TOKEN_PROGRAM,
        "executable": False,
        "data": {
            "program": "spl-token-2022",
            "parsed": {
                "type": "mint",
                "info": {
                    "decimals": 6,
                    "isInitialized": True,
                    "mintAuthority": None,
                    "freezeAuthority": None,
                    "extensions": [
                        {"extension": "metadataPointer"},
                        {"extension": "tokenMetadata"},
                    ],
                },
            },
        },
    }


def account(wallet, amount="1000000", account_id=None):
    return {
        "pubkey": account_id or encode_key(bytes([7]) * 32),
        "account": {
            "owner": TOKEN_PROGRAM,
            "executable": False,
            "data": {
                "program": "spl-token-2022",
                "parsed": {
                    "type": "account",
                    "info": {
                        "owner": wallet,
                        "mint": MINT,
                        "state": "initialized",
                        "isNative": False,
                        "tokenAmount": {"amount": amount, "decimals": 6},
                    },
                },
            },
        },
    }


@pytest.mark.parametrize(
    "amount,price,code",
    [
        ("1000000", Decimal("2"), None),
        ("999999", Decimal("2"), "insufficient_sbud"),
        ("1000000", Decimal("1.999999"), "insufficient_sbud"),
        ("1000000", Decimal("NaN"), "eligibility_unavailable"),
        ("1000000", Decimal("Infinity"), "eligibility_unavailable"),
        ("1000000", True, "eligibility_unavailable"),
    ],
)
async def test_exact_dollar_gate(key, amount, price, code):
    now = datetime(2026, 10, 19, 12, tzinfo=UTC)
    stamp = int(now.timestamp())
    service = Eligibility(None)
    service._rpc = AsyncMock(
        side_effect=[
            MAINNET_GENESIS,
            {"context": {"slot": 100}, "value": mint_record()},
            {"context": {"slot": 101}, "value": [account(address(key), amount)]},
            stamp - 10,
            stamp - 5,
        ]
    )
    service._json = AsyncMock(
        return_value={MINT: {"usdPrice": price, "decimals": 6, "blockId": 99}}
    )
    if code:
        with pytest.raises(AuthError, match=code):
            await service.verify(address(key), lambda: now)
    else:
        (await service.verify(address(key), lambda: now)).check(address(key), stamp)


@pytest.mark.parametrize(
    "price_age,balance_age", [(301, 5), (17 * 3600, 5), (-1, 5), (1, 61), (1, -1)]
)
async def test_stale_or_future_observations(key, price_age, balance_age):
    now = datetime(2026, 10, 19, 12, tzinfo=UTC)
    stamp = int(now.timestamp())
    service = Eligibility(None)
    service._rpc = AsyncMock(
        side_effect=[
            MAINNET_GENESIS,
            {"context": {"slot": 100}, "value": mint_record()},
            {"context": {"slot": 101}, "value": [account(address(key))]},
            stamp - price_age,
            stamp - balance_age,
        ]
    )
    service._json = AsyncMock(
        return_value={MINT: {"usdPrice": Decimal("3"), "decimals": 6, "blockId": 99}}
    )
    with pytest.raises(AuthError, match="eligibility_stale"):
        await service.verify(address(key), lambda: now)


@pytest.mark.parametrize(
    "field,value",
    [("owner", "other"), ("mint", "other"), ("state", "frozen"), ("isNative", True)],
)
def test_wrong_token_accounts(key, field, value):
    record = account(address(key))
    record["account"]["data"]["parsed"]["info"][field] = value
    with pytest.raises(ValueError):
        balance([record], address(key))


def test_multiple_accounts_and_duplicates(key):
    wallet = address(key)
    first, second = (
        account(wallet),
        account(wallet, "2000000", encode_key(bytes([8]) * 32)),
    )
    assert balance([first, second], wallet) == 3000000
    with pytest.raises(ValueError):
        balance([first, first], wallet)
    record = mint_record()
    record["data"]["parsed"]["info"]["extensions"].append({"extension": "transferHook"})
    with pytest.raises(ValueError):
        validate_mint(record)


@pytest.mark.parametrize(
    "fault", ["chain", "missing_mint", "missing_price", "rpc_error", "old_slot"]
)
async def test_dependencies_fail_closed(key, fault):
    now = datetime(2026, 10, 19, 12, tzinfo=UTC)
    stamp = int(now.timestamp())
    values = [
        MAINNET_GENESIS,
        {"context": {"slot": 100}, "value": mint_record()},
        {"context": {"slot": 101}, "value": [account(address(key))]},
        stamp,
        stamp,
    ]
    if fault == "chain":
        values[0] = "devnet"
    if fault == "missing_mint":
        values[1]["value"] = None
    if fault == "old_slot":
        values[2]["context"]["slot"] = 99
    service = Eligibility(None)
    service._rpc = AsyncMock(side_effect=OSError if fault == "rpc_error" else values)
    service._json = AsyncMock(
        return_value={}
        if fault == "missing_price"
        else {MINT: {"usdPrice": Decimal("3"), "decimals": 6, "blockId": 99}}
    )
    with pytest.raises(AuthError):
        await service.verify(address(key), lambda: now)


async def test_https_wallet_ui_owner_and_guest_flow(
    tls_client, hass, owner_token, payload, key, calls
):
    auth = hass.data[DOMAIN].authenticator
    auth.wallet_enabled = True
    auth.manager.wallet_enabled = True
    auth.eligibility = AsyncMock()
    auth.eligibility.verify.side_effect = lambda wallet, now: Evidence(
        wallet, int(now().timestamp()), int(now().timestamp()), monotonic() + 30
    )
    owner = {"Authorization": "Bearer " + owner_token}
    result = await tls_client.post(
        BASE + "/wallet/owner",
        headers=owner,
        json={
            "operation": "create",
            "payload": payload | {"wallet_address": address(key)},
        },
    )
    assert result.status == 200, await result.text()
    grant = await result.json()
    result = await tls_client.post(
        BASE + "/invitations", headers=owner, json={"grant_id": grant["grant_id"]}
    )
    invite = (await result.json())["invitation"]
    guest = {"Authorization": "SolbuddyInvite " + invite}
    assert (
        await tls_client.post(BASE + "/session", headers=guest, json={})
    ).status == 403
    result = await tls_client.post(BASE + "/wallet/challenge", headers=guest, json={})
    assert result.status == 200, await result.text()
    challenge = await result.json()
    result = await tls_client.post(
        BASE + "/wallet/verify", headers=guest, json={"signature": sign(key, challenge)}
    )
    assert result.status == 200, await result.text()
    token = (await result.json())["session_token"]
    result = await tls_client.post(
        BASE + "/execute",
        headers={
            "Authorization": "SolbuddySession " + token,
            "X-Solbuddy-Sequence": "1",
        },
        json={"entity_id": "light.guest_room", "action": "turn_on", "parameters": {}},
    )
    assert result.status == 200 and len(calls) == 1
    session_headers = {
        "Authorization": "SolbuddySession " + token,
        "X-Solbuddy-Sequence": "2",
    }
    result = await tls_client.post(
        BASE + "/wallet/renew-challenge", headers=session_headers, json={}
    )
    assert result.status == 200
    renewal_proof = sign(key, await result.json())
    session_headers["X-Solbuddy-Sequence"] = "3"
    result = await tls_client.post(
        BASE + "/wallet/renew",
        headers=session_headers,
        json={"signature": renewal_proof},
    )
    assert result.status == 200
    replacement = (await result.json())["session_token"]
    assert replacement != token
    session_headers["X-Solbuddy-Sequence"] = "4"
    assert (
        await tls_client.get(BASE + "/permissions", headers=session_headers)
    ).status == 401
    page = await tls_client.get(BASE + "/wallet/ui")
    assert (
        page.status == 200
        and "frame-ancestors 'none'" in page.headers["Content-Security-Policy"]
    )
    assert token not in await page.text()
    assert (await tls_client.get(BASE + "/wallet/client.js")).status == 200
    auth.wallet_enabled = False
    assert (await tls_client.get(BASE + "/wallet/ui")).status == 200
    assert (
        await tls_client.post(BASE + "/wallet/challenge", headers=guest, json={})
    ).status == 404


def test_mainnet_identity_live_reference():
    # Public mainnet getGenesisHash, independently queried 2026-10-19.
    assert MAINNET_GENESIS == "5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d"


async def test_failed_renewal_does_not_extend_session(wallet_setup, key):
    auth, grant, invite, item, service = wallet_setup
    proof = sign(key, auth.challenge(item, ORIGIN, renewal=False))
    issued = await auth.wallet_verify(item, ORIGIN, proof, renewal=False)
    original = auth._sessions[grant.grant_id]
    expiry, deadline = original.expires_at, original.deadline
    proof = sign(key, auth.challenge(original, ORIGIN, renewal=True))
    service.verify.side_effect = AuthError(503, "eligibility_stale")
    with pytest.raises(AuthError, match="eligibility_stale"):
        await auth.wallet_verify(original, ORIGIN, proof, renewal=True)
    assert auth._sessions[grant.grant_id] is original
    assert (original.expires_at, original.deadline) == (expiry, deadline)
    async with auth.request(issued["session_token"], 1) as current:
        auth.assert_live(current)
    with pytest.raises(AuthError, match="invalid_wallet_proof"):
        await auth.wallet_verify(original, ORIGIN, proof, renewal=True)


async def test_audit_failure_prevents_wallet_session(wallet_setup, key, manager):
    from custom_components.solbuddy_access.storage import StorageUnavailable

    auth, grant, invite, item, service = wallet_setup
    proof = sign(key, auth.challenge(item, ORIGIN, renewal=False))
    with patch.object(manager.audit, "append", side_effect=StorageUnavailable):
        with pytest.raises(StorageUnavailable):
            await auth.wallet_verify(item, ORIGIN, proof, renewal=False)
    assert not auth._sessions


@pytest.mark.parametrize(
    "operation", ["owner", "challenge", "verify", "renew-challenge", "renew"]
)
async def test_wallet_routes_reject_anonymous(tls_client, hass, operation):
    auth = hass.data[DOMAIN].authenticator
    auth.wallet_enabled = True
    result = await tls_client.post(BASE + "/wallet/" + operation, json={})
    assert result.status == 401


async def test_wallet_owner_rejects_admin(
    tls_client, hass, owner_token, hass_admin_user
):
    auth = hass.data[DOMAIN].authenticator
    auth.wallet_enabled = True
    # The bearer is valid, but the current identity is no longer the owner.
    with patch(
        "homeassistant.auth.AuthManager.async_get_user", return_value=hass_admin_user
    ):
        result = await tls_client.post(
            BASE + "/wallet/owner",
            headers={"Authorization": "Bearer " + owner_token},
            json={"operation": "list", "payload": {}},
        )
    assert result.status in (401, 403)


@pytest.mark.parametrize(
    "status,raw",
    [
        (429, b"provider secret"),
        (302, b""),
        (200, b"x" * 262145),
        (200, b'{"price":NaN}'),
        (200, b"not-json"),
    ],
)
async def test_provider_http_failures(status, raw):
    from unittest.mock import MagicMock

    response = MagicMock(status=status)

    async def chunks(size):
        for offset in range(0, len(raw), size):
            yield raw[offset : offset + size]

    response.content.iter_chunked.side_effect = chunks
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=response)
    context.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock()
    session.request.return_value = context
    with pytest.raises((AuthError, ValueError)):
        await Eligibility(session)._json("GET", "https://provider.example")
    assert session.request.call_args.kwargs["allow_redirects"] is False


def test_provider_file_secrets_and_invalid_fields(tmp_path):
    from custom_components.solbuddy_access.eligibility import load_provider_config

    (tmp_path / "secrets.yaml").write_text("test_jupiter: synthetic-provider-key\n")
    config = tmp_path / "solbuddy_access_wallet.yaml"
    config.write_text("jupiter_api_key: !secret test_jupiter\n")
    assert load_provider_config(tmp_path) == (
        "https://api.mainnet-beta.solana.com",
        "synthetic-provider-key",
    )
    config.write_text("minimum_usd: 0\n")
    with pytest.raises(ValueError, match="configuration unavailable"):
        load_provider_config(tmp_path)
