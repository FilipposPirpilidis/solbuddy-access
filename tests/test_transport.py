"""Transport policy boundaries, including real HA forwarded middleware."""

from ipaddress import ip_network
from unittest.mock import Mock

import pytest
from aiohttp.test_utils import make_mocked_request
from homeassistant.setup import async_setup_component

from custom_components.solbuddy_access import RuntimeData, const
from custom_components.solbuddy_access.auth import AuthError, GuestAuthenticator
from custom_components.solbuddy_access.guest_api import BASE, register
from custom_components.solbuddy_access.transport import TransportPolicy
from tests.test_guest_api import owner_token as owner_token
from tests.test_phase2 import calls as calls
from tests.test_phase2 import created as created
from tests.test_phase2 import hardware as hardware
from tests.test_phase2 import manager as manager
from tests.test_phase2 import payload as payload


def options(**overrides):
    return {
        "guest_enabled": True,
        "guest_origin": "https://remote.example",
        "local_http_enabled": True,
        "local_http_origin": "http://ha.local:8123",
        "local_http_networks": "192.168.68.0/24",
        "https_proxy_ips": "192.168.68.112",
    } | overrides


def request(peer="192.168.68.23", host="ha.local:8123", headers=None, tls=False):
    transport = Mock()
    transport.get_extra_info.side_effect = lambda key: {
        "peername": (peer, 1234),
        "ssl_object": object() if tls else None,
    }.get(key)
    return make_mocked_request(
        "POST",
        BASE + "/execute",
        headers={"Host": host} | (headers or {}),
        transport=transport,
    )


def test_local_and_direct_tls():
    policy = TransportPolicy.from_options(options())
    assert policy.check(request()) == "192.168.68.23"
    assert (
        policy.check(request(peer="8.8.8.8", host="remote.example", tls=True))
        == "8.8.8.8"
    )


@pytest.mark.parametrize(
    "peer",
    ["8.8.8.8", "192.168.69.3", "127.0.0.1", "192.168.68.112", "::ffff:192.168.68.23"],
)
def test_http_outside_network_or_proxy_denied(peer):
    with pytest.raises(AuthError):
        TransportPolicy.from_options(options()).check(request(peer=peer))


@pytest.mark.parametrize(
    "extra",
    [
        {"Origin": "http://evil.example"},
        {"Host": "evil.example"},
        {"X-Forwarded-Proto": "https"},
        {"X-Forwarded-For": "192.168.68.1"},
        {"Forwarded": "proto=https"},
    ],
)
def test_http_header_spoof_denied(extra):
    with pytest.raises(AuthError):
        TransportPolicy.from_options(options()).check(request(headers=extra))


def test_ha_proxy_cannot_fall_back_to_local():
    with pytest.raises(AuthError):
        TransportPolicy.from_options(options()).check(
            request(), [ip_network("192.168.68.23/32")]
        )


@pytest.mark.parametrize(
    "network",
    [
        "0.0.0.0/0",
        "192.0.0.0/8",
        "8.8.8.8/32",
        "169.254.0.0/16",
        "::/0",
        "",
        "192.168.68.1/24",
    ],
)
def test_invalid_local_network(network):
    with pytest.raises(ValueError):
        TransportPolicy.from_options(options(local_http_networks=network))


def test_old_options_remain_https_only():
    policy = TransportPolicy.from_options(
        {"guest_enabled": True, "guest_origin": "https://remote.example"}
    )
    assert not policy.local_origin and not policy.proxy_ips
    with pytest.raises(AuthError):
        policy.check(request())


@pytest.fixture(params=[False, True], ids=["local_http", "https_proxy"])
async def transport_client(
    request, hass, aiohttp_client, socket_enabled, manager, created
):
    proxy = request.param
    config = (
        {"use_x_forwarded_for": True, "trusted_proxies": ["127.0.0.1"]} if proxy else {}
    )
    assert await async_setup_component(hass, "http", {"http": config})
    auth = GuestAuthenticator(manager, enabled=True)
    runtime = RuntimeData(manager.storage, auth, manager)
    hass.data[const.DOMAIN] = runtime
    register(hass)
    client = await aiohttp_client(hass.http.app)
    origin = str(client.make_url("/")).rstrip("/")
    runtime.transport_policy = TransportPolicy.from_options(
        options(
            local_http_origin=origin,
            local_http_networks="127.0.0.1/32",
            https_proxy_ips="127.0.0.1" if proxy else "",
        )
    )
    forwarded = (
        {
            "X-Forwarded-For": "8.8.8.8",
            "X-Forwarded-Proto": "https",
            "X-Forwarded-Host": "remote.example",
        }
        if proxy
        else {}
    )
    return client, forwarded, runtime


async def test_invite_exchange_execute_both_transports(
    transport_client, owner_token, created, calls
):
    client, forwarded, runtime = transport_client
    result = await client.post(
        BASE + "/invitations",
        headers=forwarded | {"Authorization": "Bearer " + owner_token},
        json={"grant_id": created.grant_id},
    )
    assert result.status == 200, await result.text()
    invite = (await result.json())["invitation"]
    result = await client.post(
        BASE + "/session",
        headers=forwarded | {"Authorization": "SolbuddyInvite " + invite},
        json={},
    )
    assert result.status == 200, await result.text()
    token = (await result.json())["session_token"]
    headers = forwarded | {
        "Authorization": "SolbuddySession " + token,
        "X-Solbuddy-Sequence": "1",
    }
    result = await client.post(
        BASE + "/execute",
        headers=headers,
        json={"entity_id": "light.guest_room", "action": "turn_on", "parameters": {}},
    )
    assert result.status == 200, await result.text()
    assert len(calls) == 1
    assert (
        await client.post(BASE + "/execute", headers=headers, json={})
    ).status == 409
    runtime.authenticator.close()
    assert (await client.get(BASE + "/permissions", headers=headers)).status == 404


@pytest.mark.parametrize(
    "change",
    [
        {"X-Forwarded-Proto": "http"},
        {"X-Forwarded-Proto": "https, http"},
        {"X-Forwarded-For": "192.168.68.1, 8.8.8.8"},
        {"X-Forwarded-Host": "evil.example"},
        {"X-Forwarded-Host": "ha.local:8123"},
        {"Forwarded": "proto=https"},
    ],
)
async def test_proxy_downgrade_and_spoofing(transport_client, change, calls):
    client, forwarded, runtime = transport_client
    result = await client.post(BASE + "/session", headers=forwarded | change, json={})
    assert result.status in (400, 403)
    assert calls == []


async def test_stripped_proxy_headers_and_untrusted_proxy(transport_client, calls):
    client, forwarded, runtime = transport_client
    if forwarded:
        assert (await client.post(BASE + "/session", json={})).status == 403
        runtime.transport_policy = TransportPolicy.from_options(
            options(
                local_http_origin=str(client.make_url("/")).rstrip("/"),
                local_http_networks="127.0.0.1/32",
                https_proxy_ips="192.168.68.112",
            )
        )
        assert (
            await client.post(BASE + "/session", headers=forwarded, json={})
        ).status == 403
    else:
        assert (
            await client.post(
                BASE + "/session",
                headers={"X-Forwarded-For": "8.8.8.8", "X-Forwarded-Proto": "https"},
                json={},
            )
        ).status == 400
    assert calls == []


def test_cloud_request_cannot_use_local_exception():
    from hass_nabucasa import remote

    token = remote.is_cloud_request.set(True)
    try:
        with pytest.raises(AuthError):
            TransportPolicy.from_options(options()).check(request())
    finally:
        remote.is_cloud_request.reset(token)
