"""Native owner management, HA trusted forwarding and scoped session handoff."""

import asyncio
from dataclasses import replace
from ipaddress import ip_network
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.solbuddy_access import RuntimeData
from custom_components.solbuddy_access.auth import AuthError
from custom_components.solbuddy_access.const import DOMAIN
from custom_components.solbuddy_access.guest_api import BASE, register
from custom_components.solbuddy_access.transport import (
    HATransportPolicy,
    ha_transport_policy,
)
from tests.test_guest_api import owner_token as owner_token
from tests.test_phase2 import calls as calls
from tests.test_phase2 import hardware as hardware
from tests.test_phase2 import manager as manager
from tests.test_phase2 import payload as payload
from tests.test_transport import request
from tests.test_wallet import key as key
from tests.test_wallet import sign
from tests.test_wallet import wallet_setup as wallet_setup


def policy():
    return HATransportPolicy(
        https_origin="https://fphomebuddy.uk",
        https_origins=("https://fphomebuddy.uk",),
        local_origins=("http://homeassistant.local:8123",),
        local_networks=(ip_network("192.168.68.0/24"),),
    )


def test_auto_local_and_tls():
    assert policy().check(request(host="homeassistant.local:8123")) == "192.168.68.23"
    assert policy().check(
        request(host="fphomebuddy.uk", tls=True).clone(scheme="https")
    )
    with pytest.raises(AuthError):
        policy().check(request(host="homeassistant.local:8123"), https_only=True)


@pytest.mark.parametrize(
    "peer,host,headers",
    [
        ("8.8.8.8", "homeassistant.local:8123", {}),
        ("192.168.68.23", "evil.example:8123", {}),
        (
            "192.168.68.23",
            "homeassistant.local:8123",
            {"Origin": "http://evil.example"},
        ),
        ("192.168.68.23", "homeassistant.local:8123", {"Sec-Fetch-Site": "cross-site"}),
        ("192.168.68.23", "homeassistant.local:8123", {"X-Forwarded-Proto": "https"}),
        ("192.168.68.112", "homeassistant.local:8123", {}),
        (
            "192.168.68.112",
            "homeassistant.local:8123",
            {"CF-Connecting-IP": "192.168.68.23"},
        ),
    ],
)
def test_no_remote_local_fallback(peer, host, headers):
    with pytest.raises(AuthError):
        policy().check(
            request(peer=peer, host=host, headers=headers),
            [ip_network("192.168.68.112/32")],
        )


async def test_urls_and_networks_derive_from_ha(hass, monkeypatch):
    hass.config.external_url = "https://fphomebuddy.uk"
    hass.config.internal_url = "http://homeassistant.local:8123"
    monkeypatch.setattr(
        "custom_components.solbuddy_access.transport.async_get_adapters",
        AsyncMock(
            return_value=[
                {
                    "enabled": True,
                    "ipv4": [{"address": "192.168.68.10", "network_prefix": 24}],
                }
            ]
        ),
    )
    result = await ha_transport_policy(hass, {})
    assert result.https_origins == ("https://fphomebuddy.uk",)
    assert "http://homeassistant.local:8123" in result.local_origins
    assert result.check(request(host="homeassistant.local:8123"))
    monkeypatch.setattr(
        "custom_components.solbuddy_access.transport.async_get_adapters",
        AsyncMock(side_effect=OSError),
    )
    result = await ha_transport_policy(hass, {})
    assert result.check(request(host="fphomebuddy.uk", tls=True).clone(scheme="https"))
    with pytest.raises(AuthError):
        result.check(request(host="homeassistant.local:8123"))


@pytest.fixture
async def tunnel(hass, aiohttp_client, socket_enabled, wallet_setup):
    assert await async_setup_component(
        hass,
        "http",
        {"http": {"use_x_forwarded_for": True, "trusted_proxies": ["127.0.0.1"]}},
    )
    auth, grant, invite, item, service = wallet_setup
    runtime = RuntimeData(
        auth.manager.storage, auth, auth.manager, transport_policy=policy()
    )
    hass.data[DOMAIN] = runtime
    register(hass)
    client = await aiohttp_client(hass.http.app)
    headers = {
        "Host": "fphomebuddy.uk",
        "X-Forwarded-For": "198.51.100.10, 203.0.113.20",
        "X-Forwarded-Proto": "https",
        "CF-Connecting-IP": "198.51.100.10",
    }
    return client, headers, runtime


async def test_tunnel_signed_login_and_local_handoff(
    tunnel, wallet_setup, key, hass, calls
):
    client, headers, runtime = tunnel
    auth, grant, invite, item, service = wallet_setup
    guest = headers | {"Authorization": "SolbuddyInvite " + invite["invitation"]}
    result = await client.post(BASE + "/wallet/challenge", headers=guest, json={})
    assert result.status == 200, await result.text()
    challenge = await result.json()
    assert "https://fphomebuddy.uk/" in challenge["message"]
    result = await client.post(
        BASE + "/wallet/verify", headers=guest, json={"signature": sign(key, challenge)}
    )
    assert result.status == 200, await result.text()
    session = await result.json()
    headers_session = headers | {
        "Authorization": "SolbuddySession " + session["session_token"],
        "X-Solbuddy-Sequence": "1",
    }
    result = await client.post(
        BASE + "/session/transfer", headers=headers_session, json={}
    )
    assert result.status == 200
    code = (await result.json())["transfer_code"]
    # Loopback represents the LAN only in this test. Temporarily remove its
    # proxy classification for direct requests. Forwarded requests still use
    # the real HA middleware.
    runtime.transport_policy = replace(
        policy(), local_networks=(ip_network("127.0.0.1/32"),)
    )

    async def local_post(*args, **kwargs):
        with patch.object(hass.http, "trusted_proxies", []):
            return await client.post(*args, **kwargs)

    result = await local_post(
        BASE + "/session/claim",
        headers={
            "Host": "homeassistant.local:8123",
            "Authorization": "SolbuddyTransfer " + code,
        },
        json={},
    )
    assert result.status == 200, await result.text()
    moved = await result.json()
    assert moved["expires_at"] == session["expires_at"]
    assert moved["session_token"] != session["session_token"]
    result = await local_post(
        BASE + "/execute",
        headers={
            "Host": "homeassistant.local:8123",
            "Authorization": "SolbuddySession " + moved["session_token"],
            "X-Solbuddy-Sequence": "1",
        },
        json={"entity_id": "light.guest_room", "action": "turn_on", "parameters": {}},
    )
    assert result.status == 200 and len(calls) == 1
    result = await local_post(
        BASE + "/wallet/renew-challenge",
        headers={
            "Host": "homeassistant.local:8123",
            "Authorization": "SolbuddySession " + moved["session_token"],
            "X-Solbuddy-Sequence": "2",
        },
        json={},
    )
    assert result.status == 403
    result = await client.get(
        BASE + "/permissions", headers=headers_session | {"X-Solbuddy-Sequence": "2"}
    )
    assert result.status == 401
    result = await local_post(
        BASE + "/session/claim",
        headers={
            "Host": "homeassistant.local:8123",
            "Authorization": "SolbuddyTransfer " + code,
        },
        json={},
    )
    assert result.status == 401


@pytest.mark.parametrize(
    "updates",
    [
        {"X-Forwarded-Proto": "http"},
        {"X-Forwarded-Proto": ""},
        {"Origin": "https://evil.example"},
        {"X-Forwarded-Host": "evil.example"},
        {"Forwarded": "proto=https"},
        {"X-Forwarded-For": "not-an-ip"},
    ],
)
async def test_bad_tunnel_forwarding_denied(tunnel, updates):
    client, headers, runtime = tunnel
    result = await client.post(
        BASE + "/wallet/challenge", headers=headers | updates, json={}
    )
    assert result.status in (400, 403)


async def test_owner_native_login_available_when_disabled(
    tunnel, hass, owner_token, hass_admin_user
):
    client, headers, runtime = tunnel
    runtime.authenticator.enabled = False
    runtime.authenticator.wallet_enabled = False
    headers = headers | {"Authorization": "Bearer " + owner_token}
    result = await client.post(
        BASE + "/wallet/owner",
        headers=headers,
        json={"operation": "status", "payload": {}},
    )
    assert result.status == 200
    result = await result.json()
    assert not result["guest_enabled"] and not result["wallet_enabled"]
    assert result["entities"][0]["entity_id"] == "light.guest_room"
    result = await client.get(BASE + "/wallet/owner-ui", allow_redirects=False)
    assert result.status == 302 and result.headers["Location"] == "/solbuddy-access"
    assert (await client.get(BASE + "/wallet/owner-panel.js")).status == 200
    result = await client.post(BASE + "/wallet/challenge", headers=headers, json={})
    assert result.status == 404
    refresh = await hass.auth.async_create_refresh_token(
        hass_admin_user, "https://example.test"
    )
    admin = hass.auth.async_create_access_token(refresh)
    result = await client.post(
        BASE + "/wallet/owner",
        headers=headers | {"Authorization": "Bearer " + admin},
        json={"operation": "status", "payload": {}},
    )
    assert result.status == 403


async def test_only_owner_can_learn_https_origin(
    tunnel, hass, owner_token, monkeypatch
):
    client, headers, runtime = tunnel
    entry = MockConfigEntry(
        domain=DOMAIN, data={"storage_id": "unused"}, options={"connection_mode": "ha"}
    )
    entry.add_to_hass(hass)
    runtime.transport_options = {"connection_mode": "ha"}
    monkeypatch.setattr(
        "custom_components.solbuddy_access.transport.async_get_adapters",
        AsyncMock(return_value=[]),
    )
    result = await client.post(
        BASE + "/wallet/owner",
        headers=headers,
        json={"operation": "status", "payload": {}},
    )
    assert result.status == 401
    assert "learned_https_origin" not in entry.options
    result = await client.post(
        BASE + "/wallet/owner",
        headers=headers | {"Authorization": "Bearer " + owner_token},
        json={"operation": "status", "payload": {}},
    )
    assert result.status == 200, await result.text()
    assert entry.options["learned_https_origin"] == "https://fphomebuddy.uk"
    assert runtime.transport_options["learned_https_origin"] == "https://fphomebuddy.uk"


@pytest.mark.parametrize("fault", ["expired", "revoked", "replaced", "disabled"])
async def test_transfer_expiry_and_invalidation(
    wallet_setup, key, hass_owner_user, fault
):
    auth, grant, invite, item, service = wallet_setup
    await auth.wallet_verify(
        item,
        "https://ha.example",
        sign(key, auth.challenge(item, "https://ha.example", renewal=False)),
        renewal=False,
    )
    session = auth._sessions[grant.grant_id]
    code = auth.transfer(session)["transfer_code"]
    if fault == "expired":
        digest, old, deadline = auth._transfers[grant.grant_id]
        auth._transfers[grant.grant_id] = (digest, old, 0)
    elif fault == "revoked":
        await auth.manager.revoke(hass_owner_user.id, grant.grant_id)
    elif fault == "replaced":
        await auth.issue(hass_owner_user.id, grant.grant_id)
    else:
        auth.close()
    with pytest.raises(AuthError):
        await auth.claim(code)


async def test_transfer_race_is_single_use(wallet_setup, key):
    auth, grant, invite, item, service = wallet_setup
    await auth.wallet_verify(
        item,
        "https://ha.example",
        sign(key, auth.challenge(item, "https://ha.example", renewal=False)),
        renewal=False,
    )
    code = auth.transfer(auth._sessions[grant.grant_id])["transfer_code"]
    results = await asyncio.gather(
        auth.claim(code), auth.claim(code), return_exceptions=True
    )
    assert sum(isinstance(r, dict) for r in results) == 1
    assert sum(isinstance(r, AuthError) for r in results) == 1


async def test_ha_external_url_preferred_for_wallet_signing(hass, monkeypatch):
    hass.config.external_url = "https://remote.example"
    hass.config.internal_url = "https://ha.local"
    monkeypatch.setattr(
        "custom_components.solbuddy_access.transport.async_get_adapters",
        AsyncMock(return_value=[]),
    )
    result = await ha_transport_policy(
        hass, {"learned_https_origin": "https://another.example"}
    )
    assert result.https_origin == "https://remote.example"
    assert "https://ha.local" in result.https_origins
