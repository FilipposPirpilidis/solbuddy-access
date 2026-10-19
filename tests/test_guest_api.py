"""Real TLS and HA HTTP middleware tests, including owner invitation issuance."""

import ipaddress
import logging
import ssl
from datetime import UTC, datetime, timedelta

import pytest
from aiohttp import TCPConnector
from aiohttp.test_utils import TestServer
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from homeassistant.setup import async_setup_component

from custom_components.solbuddy_access import RuntimeData, const
from custom_components.solbuddy_access.auth import GuestAuthenticator
from custom_components.solbuddy_access.guest_api import BASE, register
from tests.test_phase2 import calls as calls
from tests.test_phase2 import created as created
from tests.test_phase2 import hardware as hardware
from tests.test_phase2 import manager as manager
from tests.test_phase2 import payload as payload


@pytest.fixture
def tls_contexts(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = tmp_path / "test-cert.pem", tmp_path / "test-key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    server = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server.load_cert_chain(cert_path, key_path)
    client = ssl.create_default_context(cafile=str(cert_path))
    return server, client


@pytest.fixture
async def owner_token(hass, hass_owner_user):
    refresh = await hass.auth.async_create_refresh_token(
        hass_owner_user, "https://example.test"
    )
    return hass.auth.async_create_access_token(refresh)


@pytest.fixture
async def tls_client(
    hass, aiohttp_client, socket_enabled, tls_contexts, manager, created, monkeypatch
):
    assert await async_setup_component(hass, "http", {"http": {}})
    assert await async_setup_component(hass, "api", {})
    assert await async_setup_component(hass, "websocket_api", {})
    auth = GuestAuthenticator(manager, enabled=True)
    runtime = RuntimeData(manager.storage, auth, manager)
    hass.data[const.DOMAIN] = runtime
    # Test-only opening of the gate, before enabling it in production source.
    monkeypatch.setattr(const, "GUEST_TRANSPORT_VERIFIED", True)
    register(hass)
    server = TestServer(hass.http.app)
    await server.start_server(ssl=tls_contexts[0])
    client = await aiohttp_client(server, connector=TCPConnector(ssl=tls_contexts[1]))
    runtime.guest_origin = str(server.make_url("/")).rstrip("/")
    return client


@pytest.fixture
async def credentials(tls_client, owner_token, created):
    result = await tls_client.post(
        BASE + "/invitations",
        headers={"Authorization": "Bearer " + owner_token},
        json={"grant_id": created.grant_id},
    )
    assert result.status == 200, await result.text()
    invitation = (await result.json())["invitation"]
    result = await tls_client.post(
        BASE + "/session",
        headers={"Authorization": "SolbuddyInvite " + invitation},
        json={},
    )
    assert result.status == 200, await result.text()
    return invitation, (await result.json())["session_token"]


def headers(token, sequence=1):
    return {
        "Authorization": "SolbuddySession " + token,
        "X-Solbuddy-Sequence": str(sequence),
    }


async def test_tls_owner_to_guest_light(tls_client, credentials, calls):
    result = await tls_client.post(
        BASE + "/execute",
        headers=headers(credentials[1]),
        json={"entity_id": "light.guest_room", "action": "turn_on", "parameters": {}},
    )
    assert result.status == 200
    assert (await result.json())["outcome"] == "dispatched"
    assert result.headers["Cache-Control"] == "no-store"
    assert result.headers.get("Access-Control-Allow-Origin") is None
    assert len(calls) == 1 and calls[0].data == {"entity_id": "light.guest_room"}


@pytest.mark.parametrize(
    "operation,method",
    [
        ("session", "post"),
        ("session/renew", "post"),
        ("permissions", "get"),
        ("check", "post"),
        ("execute", "post"),
    ],
)
async def test_no_anonymous_guest_operations(tls_client, operation, method, calls):
    result = await getattr(tls_client, method)(BASE + "/" + operation)
    assert result.status == 401
    assert calls == []


async def test_both_credential_boundaries(tls_client, credentials, owner_token, calls):
    result = await tls_client.post(
        BASE + "/execute",
        headers={"Authorization": "Bearer " + owner_token, "X-Solbuddy-Sequence": "1"},
        json={},
    )
    assert result.status == 401
    result = await tls_client.get(
        "/api/", headers={"Authorization": "Bearer " + credentials[1]}
    )
    assert result.status == 401
    result = await tls_client.post(
        BASE + "/session",
        headers={"Authorization": "SolbuddyInvite " + credentials[1]},
        json={},
    )
    assert result.status == 401
    assert calls == []


async def test_permissions_redacted(tls_client, credentials):
    result = await tls_client.get(
        BASE + "/permissions", headers=headers(credentials[1])
    )
    assert result.status == 200
    data = await result.json()
    assert set(data) == {"expires_at", "policies"}
    assert not {"registry_id", "unique_id", "guest_identifier", "created_by"} & set(
        data["policies"][0]
    )


async def test_replay_and_invalid_body_consumes_sequence(
    tls_client, credentials, calls
):
    token = credentials[1]
    result = await tls_client.post(
        BASE + "/execute", headers=headers(token), json={"grant_id": "forged"}
    )
    assert result.status == 400
    result = await tls_client.get(BASE + "/permissions", headers=headers(token))
    assert result.status == 409
    result = await tls_client.get(BASE + "/permissions", headers=headers(token, 2))
    assert result.status == 200
    assert calls == []


@pytest.mark.parametrize(
    "extra",
    [
        {"Origin": "https://evil.example"},
        {"Origin": "null"},
        {"Host": "evil.example"},
        {"X-Forwarded-Proto": "https"},
    ],
)
async def test_origin_and_proxy_denied(tls_client, credentials, extra, calls):
    result = await tls_client.post(
        BASE + "/execute", headers=headers(credentials[1]) | extra, json={}
    )
    assert result.status in (400, 403)
    assert calls == []


@pytest.mark.parametrize(
    "data", ['{"a":1,"a":2}', '{"brightness":NaN}', "[" * 1000, "x" * 8193]
)
async def test_strict_bounded_json(tls_client, credentials, data, calls):
    result = await tls_client.post(
        BASE + "/execute",
        headers=headers(credentials[1]) | {"Content-Type": "application/json"},
        data=data,
    )
    assert result.status in (400, 413)
    assert calls == []


async def test_cross_grant_payload_rejected(tls_client, credentials, calls):
    result = await tls_client.post(
        BASE + "/execute",
        headers=headers(credentials[1]),
        json={
            "grant_id": "another-grant",
            "entity_id": "light.guest_room",
            "action": "turn_on",
            "parameters": {},
        },
    )
    assert result.status == 400
    assert calls == []


async def test_revoke_live_token(
    tls_client, credentials, manager, created, hass_owner_user, calls
):
    await manager.revoke(hass_owner_user.id, created.grant_id)
    result = await tls_client.post(
        BASE + "/execute", headers=headers(credentials[1]), json={}
    )
    assert result.status == 401
    assert calls == []


async def test_refresh_rotation(tls_client, credentials):
    old = credentials[1]
    result = await tls_client.post(
        BASE + "/session/renew", headers=headers(old), json={}
    )
    assert result.status == 200
    new = (await result.json())["session_token"]
    assert (
        await tls_client.get(BASE + "/permissions", headers=headers(old, 2))
    ).status == 401
    assert (
        await tls_client.get(BASE + "/permissions", headers=headers(new))
    ).status == 200


async def test_debug_logs_never_contain_credentials(
    tls_client, owner_token, created, caplog
):
    caplog.set_level(logging.DEBUG)
    result = await tls_client.post(
        BASE + "/invitations",
        headers={"Authorization": "Bearer " + owner_token},
        json={"grant_id": created.grant_id},
    )
    invitation = (await result.json())["invitation"]
    result = await tls_client.post(
        BASE + "/session",
        headers={"Authorization": "SolbuddyInvite " + invitation},
        json={},
    )
    token = (await result.json())["session_token"]
    assert (
        await tls_client.get(BASE + "/permissions", headers=headers(token))
    ).status == 200
    assert (
        invitation not in caplog.text
        and token not in caplog.text
        and owner_token not in caplog.text
    )


async def test_http_is_rejected_even_with_forwarded_https(
    hass, aiohttp_client, socket_enabled, manager, created, monkeypatch
):
    assert await async_setup_component(hass, "http", {"http": {}})
    hass.data[const.DOMAIN] = RuntimeData(
        manager.storage,
        GuestAuthenticator(manager, enabled=True),
        manager,
        "https://127.0.0.1",
    )
    monkeypatch.setattr(const, "GUEST_TRANSPORT_VERIFIED", True)
    register(hass)
    client = await aiohttp_client(hass.http.app)
    result = await client.post(
        BASE + "/session", headers={"X-Forwarded-Proto": "https"}
    )
    assert result.status in (400, 403)


async def test_http_session_rate_limit(tls_client, credentials, calls):
    for number in range(1, 6):
        assert (
            await tls_client.get(
                BASE + "/permissions", headers=headers(credentials[1], number)
            )
        ).status == 200
    assert (
        await tls_client.get(BASE + "/permissions", headers=headers(credentials[1], 6))
    ).status == 429
    assert calls == []


async def test_chunked_body_limit(tls_client, credentials, calls):
    async def chunks():
        for _ in range(9):
            yield b"x" * 1024

    result = await tls_client.post(
        BASE + "/execute",
        headers=headers(credentials[1]) | {"Content-Type": "application/json"},
        data=chunks(),
    )
    assert result.status == 413
    assert calls == []


async def test_query_credential_rejected(tls_client, credentials, calls):
    result = await tls_client.post(
        BASE + "/execute?token=synthetic", headers=headers(credentials[1]), json={}
    )
    assert result.status == 400
    assert calls == []


async def test_admin_cannot_issue(tls_client, hass, hass_admin_user, created):
    refresh = await hass.auth.async_create_refresh_token(
        hass_admin_user, "https://example.test"
    )
    token = hass.auth.async_create_access_token(refresh)
    result = await tls_client.post(
        BASE + "/invitations",
        headers={"Authorization": "Bearer " + token},
        json={"grant_id": created.grant_id},
    )
    assert result.status == 403


async def test_disable_existing_routes(tls_client, credentials, hass, calls):
    hass.data[const.DOMAIN].authenticator.close()
    result = await tls_client.post(
        BASE + "/execute", headers=headers(credentials[1]), json={}
    )
    assert result.status == 404
    assert calls == []


async def test_guest_token_rejected_by_ha_websocket(tls_client, credentials):
    websocket = await tls_client.ws_connect("/api/websocket")
    assert (await websocket.receive_json())["type"] == "auth_required"
    await websocket.send_json({"type": "auth", "access_token": credentials[1]})
    assert (await websocket.receive_json())["type"] == "auth_invalid"
    await websocket.close()
