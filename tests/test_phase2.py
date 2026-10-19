"""Phase 2 with real HA registries, service dispatch, storage, and WebSocket API."""

import asyncio
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from homeassistant.components.light import ColorMode
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.solbuddy_access.audit import AuditStore
from custom_components.solbuddy_access.const import DOMAIN
from custom_components.solbuddy_access.executor import LightExecutor
from custom_components.solbuddy_access.grants import AccessDenied, GrantManager
from custom_components.solbuddy_access.models import Grant, ValidationError
from custom_components.solbuddy_access.storage import GrantStorage, StorageUnavailable


@pytest.fixture
def hardware(hass):
    """Synthetic footprint of the reviewed class, never a real bridge connection."""
    entry = MockConfigEntry(domain="hue")
    entry.add_to_hass(hass)
    entry._async_set_state(hass, ConfigEntryState.LOADED, None)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={("hue", "physical-light")},
    )
    record = er.async_get(hass).async_get_or_create(
        "light",
        "hue",
        "unique-light",
        config_entry=entry,
        device_id=device.id,
        suggested_object_id="guest_room",
    )
    # Exact class identity is part of adapter eligibility; other classes are denied.
    cls = type("HueLight", (), {"__module__": "homeassistant.components.hue.v2.light"})
    entity = cls()
    entity.unique_id = record.unique_id
    entity.device = SimpleNamespace(id="physical-light")
    entity.available = True
    entity.supported_color_modes = {ColorMode.BRIGHTNESS}
    hass.data["light"] = SimpleNamespace(
        get_entity=lambda entity_id: entity if entity_id == record.entity_id else None,
    )
    hass.states.async_set(record.entity_id, "off")
    yield SimpleNamespace(entry=entry, device=device, record=record, entity=entity)
    entry._async_set_state(hass, ConfigEntryState.NOT_LOADED, None)


@pytest.fixture
def payload(hardware):
    now = dt_util.utcnow()
    return {
        "guest_display_name": "Private Guest Name",
        "starts_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=72)).isoformat(),
        "policies": [
            {"entity_id": hardware.record.entity_id, "actions": ["turn_on", "turn_off"]}
        ],
    }


@pytest.fixture
async def manager(hass, hardware):
    storage_id = str(uuid4())
    storage = GrantStorage(hass, storage_id)
    await storage.async_initialize()
    audit = AuditStore(hass, storage_id)
    await audit.load(initialize=True)
    return GrantManager(hass, storage, audit, LightExecutor(hass))


@pytest.fixture
async def created(manager, hass_owner_user, payload):
    return await manager.create(hass_owner_user.id, payload)


@pytest.fixture
def calls(hass):
    calls = []

    async def handle(call):
        calls.append(call)

    hass.services.async_register("light", "turn_on", handle)
    hass.services.async_register("light", "turn_off", handle)
    return calls


def request(entity_id="light.guest_room", action="turn_on", parameters=None):
    return {"entity_id": entity_id, "action": action, "parameters": parameters or {}}


async def test_72_hour_single_light(manager, created, calls, hass_owner_user):
    assert created.expires_at - created.starts_at == timedelta(hours=72)
    assert (await manager.execute(created.grant_id, request()))[
        "outcome"
    ] == "dispatched"
    assert len(calls) == 1
    assert calls[0].domain == "light"
    assert calls[0].service == "turn_on"
    assert calls[0].data == {"entity_id": "light.guest_room"}
    assert calls[0].context.user_id is None
    result = await manager.revoke(hass_owner_user.id, created.grant_id)
    assert result["grant"]["status"] == "revoked"
    assert (await manager.execute(created.grant_id, request()))["outcome"] == "denied"
    assert len(calls) == 1


@pytest.mark.parametrize(
    "action_request",
    [
        request("light.other"),
        request("lock.front_door", "unlock"),
        request("camera.front"),
        request("alarm_control_panel.home"),
        request(action="set_brightness", parameters={"brightness": 100}),
        request(action="toggle"),
        request(parameters={"service": "lock.unlock"}),
        request(parameters={"entity_id": "light.other"}),
        request(parameters={"transition": 5}),
    ],
)
async def test_denial_never_dispatches(manager, created, calls, action_request):
    assert (await manager.execute(created.grant_id, action_request))[
        "outcome"
    ] == "denied"
    assert calls == []


async def test_bounded_brightness(manager, payload, hass_owner_user, calls):
    payload["policies"][0].update(
        actions=["turn_on", "set_brightness"],
        brightness_min=20,
        brightness_max=180,
        turn_on_brightness=100,
    )
    grant = await manager.create(hass_owner_user.id, payload)
    await manager.execute(grant.grant_id, request())
    assert calls[0].data == {"entity_id": "light.guest_room", "brightness": 100}
    for value in (0, 19, 181, True, "100", float("nan")):
        assert (
            await manager.execute(
                grant.grant_id,
                request(action="set_brightness", parameters={"brightness": value}),
            )
        )["outcome"] == "denied"
    assert len(calls) == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("registry_id", "forged"),
        ("reviewed_physical_device", True),
        ("device_id", "forged"),
    ],
)
async def test_reject_client_evidence(manager, payload, hass_owner_user, field, value):
    payload["policies"][0][field] = value
    with pytest.raises(ValidationError):
        await manager.create(hass_owner_user.id, payload)


@pytest.mark.parametrize(
    "module,name",
    [
        ("homeassistant.components.hue.v2.group", "HueGroupedLight"),
        ("homeassistant.components.template.light", "LightTemplate"),
        ("custom_components.hue.light", "HueLight"),
    ],
)
async def test_unknown_or_forwarding_implementation(
    hardware, manager, payload, hass_owner_user, module, name
):
    hardware.entity.__class__ = type(name, (), {"__module__": module})
    with pytest.raises(ValidationError):
        await manager.create(hass_owner_user.id, payload)


async def test_replaced_device_denied(hass, manager, created, hardware, calls):
    er.async_get(hass).async_update_entity(
        hardware.record.entity_id, new_unique_id="replaced"
    )
    hardware.entity.unique_id = "replaced"
    assert (await manager.execute(created.grant_id, request()))["outcome"] == "denied"
    assert calls == []


async def test_expiry_after_admission_denies(manager, created, calls):
    original = manager.audit.append

    async def expire(event, *args, **kwargs):
        result = await original(event, *args, **kwargs)
        if event == "admitted":
            manager.now = lambda: created.expires_at
        return result

    with patch.object(manager.audit, "append", side_effect=expire):
        assert (await manager.execute(created.grant_id, request()))[
            "outcome"
        ] == "denied"
    assert calls == []


async def test_revoke_wins_gate(manager, created, hass_owner_user, calls):
    entered, release = asyncio.Event(), asyncio.Event()
    original = manager.storage.async_revoke

    async def held(*args, **kwargs):
        entered.set()
        await release.wait()
        return await original(*args, **kwargs)

    with patch.object(manager.storage, "async_revoke", side_effect=held):
        revocation = asyncio.create_task(
            manager.revoke(hass_owner_user.id, created.grant_id)
        )
        await entered.wait()
        execution = asyncio.create_task(manager.execute(created.grant_id, request()))
        release.set()
        await revocation
        assert (await execution)["outcome"] == "denied"
    assert calls == []


async def test_execution_wins_gate(hass, manager, created, hass_owner_user):
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def service(call):
        calls.append(call)
        entered.set()
        await release.wait()

    hass.services.async_register("light", "turn_on", service)
    execution = asyncio.create_task(manager.execute(created.grant_id, request()))
    await entered.wait()
    revocation = asyncio.create_task(
        manager.revoke(hass_owner_user.id, created.grant_id)
    )
    release.set()
    assert (await execution)["outcome"] == "dispatched"
    assert (await revocation)["grant"]["status"] == "revoked"
    assert (await manager.execute(created.grant_id, request()))["outcome"] == "denied"
    assert len(calls) == 1


async def test_audit_failure_blocks_execution_but_not_revoke(
    manager, created, hass_owner_user, calls
):
    with patch.object(manager.audit.store, "async_save", new=AsyncMock()):
        with pytest.raises(StorageUnavailable):
            await manager.execute(created.grant_id, request())
        result = await manager.revoke(hass_owner_user.id, created.grant_id)
    assert result["grant"]["status"] == "revoked"
    assert result["audit_degraded"]
    assert calls == []


async def test_clock_fault_preserves_revocation(
    manager, created, hass_owner_user, calls
):
    manager._wall -= timedelta(seconds=60)
    with pytest.raises(AccessDenied, match="clock_untrusted"):
        await manager.execute(created.grant_id, request())
    assert (await manager.revoke(hass_owner_user.id, created.grant_id))["grant"][
        "status"
    ] == "revoked"
    assert calls == []


async def test_timeout_never_retries(hass, manager, created):
    calls = []

    async def slow(call):
        calls.append(call)
        await asyncio.Event().wait()

    hass.services.async_register("light", "turn_on", slow)
    manager.execution_timeout = 0.01
    assert (await manager.execute(created.grant_id, request()))["outcome"] == "unknown"
    assert len(calls) == 1


async def test_redaction_and_correlation(manager, created, calls, hass):
    await manager.execute(created.grant_id, request())
    data = await hass.async_add_executor_job(manager.audit._read)
    assert "Private Guest Name" not in str(data)
    assert "owner" not in str(data)
    admitted, completed = data["records"][-2:]
    assert admitted["event"] == "admitted" and completed["event"] == "dispatched"
    assert admitted["operation_id"] == completed["operation_id"]
    assert completed["action"] == "turn_on"


async def test_legacy_grant_stays_revocable(manager, grant, hass_owner_user, calls):
    raw = grant.to_dict()
    raw["schema_version"] = 1
    for policy in raw["policies"]:
        policy.pop("device_id")
        policy.pop("unique_id")
    old = Grant.from_dict(raw)
    await manager.storage.async_add(old)
    manager._locks[old.grant_id] = asyncio.Lock()
    assert (await manager.execute(old.grant_id, request()))[
        "reason"
    ] == "legacy_binding"
    assert (await manager.revoke(hass_owner_user.id, old.grant_id))["grant"][
        "status"
    ] == "revoked"
    assert calls == []


@pytest.fixture
async def runtime(hass, manager):
    from homeassistant.setup import async_setup_component

    from custom_components.solbuddy_access import RuntimeData
    from custom_components.solbuddy_access.api import register
    from custom_components.solbuddy_access.auth import GuestAuthenticator

    assert await async_setup_component(hass, "websocket_api", {})
    hass.data[DOMAIN] = RuntimeData(manager.storage, GuestAuthenticator(), manager)
    register(hass)
    return manager


@pytest.fixture
async def owner_client(hass, hass_owner_user, hass_ws_client, runtime):
    refresh = await hass.auth.async_create_refresh_token(
        hass_owner_user, "https://example.test"
    )
    return await hass_ws_client(
        access_token=hass.auth.async_create_access_token(refresh)
    )


async def command(client, operation, payload=None):
    await client.send_json_auto_id(
        {"type": f"solbuddy_access/grants/{operation}", "payload": payload or {}}
    )
    return await client.receive_json()


async def test_owner_websocket_lifecycle(owner_client, payload, calls):
    result = await command(owner_client, "create", payload)
    assert result["success"], result
    grant_id = result["result"]["grant_id"]
    assert (await command(owner_client, "list"))["result"]["grants"][0][
        "grant_id"
    ] == grant_id
    assert (await command(owner_client, "get", {"grant_id": grant_id}))["result"][
        "status"
    ] == "active"
    assert (await command(owner_client, "check", request() | {"grant_id": grant_id}))[
        "result"
    ]["allowed"]
    assert (await command(owner_client, "revoke", {"grant_id": grant_id}))["result"][
        "grant"
    ]["status"] == "revoked"
    assert not (
        await command(owner_client, "check", request() | {"grant_id": grant_id})
    )["result"]["allowed"]
    assert calls == []  # No management command dispatches a device action.


async def test_admin_rejected(runtime, hass_ws_client):
    client = await hass_ws_client()
    for operation in ("create", "list", "get", "check", "revoke"):
        result = await command(client, operation)
        assert not result["success"]
        assert result["error"]["code"] == "not_allowed"


async def test_no_execute_command(owner_client):
    result = await command(owner_client, "execute", request())
    assert not result["success"]
    assert result["error"]["code"] == "unknown_command"


async def test_owner_revalidated_and_unload(owner_client, runtime, hass_owner_user):
    with patch("homeassistant.auth.AuthManager.async_get_user", return_value=None):
        assert (await command(owner_client, "list"))["error"]["code"] == "not_allowed"
    await runtime.close()
    assert (await command(owner_client, "list"))["error"]["code"] == "not_allowed"


async def test_persistence_restarts_revocation(
    hass, manager, created, hass_owner_user, calls
):
    await manager.revoke(hass_owner_user.id, created.grant_id)
    storage_id = manager.storage._store.key.split(".", 1)[1]
    await manager.close()
    storage = GrantStorage(hass, storage_id)
    await storage.async_load()
    audit = AuditStore(hass, storage_id)
    await audit.load(initialize=False)
    restored = GrantManager(hass, storage, audit, LightExecutor(hass))
    assert (await restored.execute(created.grant_id, request()))["outcome"] == "denied"
    assert calls == []


async def test_failed_revoke_latches_closed(manager, created, hass_owner_user, calls):
    with patch.object(manager.storage._store, "async_save", new=AsyncMock()):
        with pytest.raises(StorageUnavailable):
            await manager.revoke(hass_owner_user.id, created.grant_id)
    with pytest.raises(StorageUnavailable):
        await manager.execute(created.grant_id, request())
    assert calls == []


async def test_completion_audit_failure_reports_unknown(manager, created, calls):
    original = manager.audit.append

    async def fail_completion(event, *args, **kwargs):
        if event == "dispatched":
            with patch.object(manager.audit.store, "async_save", new=AsyncMock()):
                return await original(event, *args, **kwargs)
        return await original(event, *args, **kwargs)

    with patch.object(manager.audit, "append", side_effect=fail_completion):
        assert (await manager.execute(created.grant_id, request()))[
            "outcome"
        ] == "unknown"
    with pytest.raises(StorageUnavailable):
        await manager.execute(created.grant_id, request())
    assert len(calls) == 1


async def test_binding_changed_during_audit(manager, created, calls, hardware):
    original = manager.audit.append

    async def change(event, *args, **kwargs):
        result = await original(event, *args, **kwargs)
        if event == "admitted":
            hardware.entity.available = False
        return result

    with patch.object(manager.audit, "append", side_effect=change):
        assert (await manager.execute(created.grant_id, request()))[
            "outcome"
        ] == "denied"
    assert calls == []


async def test_pending_grant_denied(manager, payload, hass_owner_user, calls):
    payload["starts_at"] = (dt_util.utcnow() + timedelta(hours=1)).isoformat()
    grant = await manager.create(hass_owner_user.id, payload)
    assert (await manager.execute(grant.grant_id, request()))[
        "reason"
    ] == "grant_pending"
    assert calls == []


async def test_queue_limit_and_unload_deny_new_work(manager, created, calls):
    manager._waiting[created.grant_id] = 8
    with pytest.raises(AccessDenied, match="queue_full"):
        await manager.execute(created.grant_id, request())
    manager._waiting[created.grant_id] = 0
    await manager.close()
    with pytest.raises(AccessDenied, match="integration_unavailable"):
        await manager.execute(created.grant_id, request())
    assert calls == []


async def test_missing_audit_on_reload_still_allows_revoke(
    hass, manager, created, hass_owner_user, calls
):
    storage_id = manager.storage._store.key.split(".", 1)[1]
    await manager.audit.store.async_remove()
    audit = AuditStore(hass, storage_id)
    with pytest.raises(StorageUnavailable):
        await audit.load(initialize=False)
    manager.audit = audit
    assert (await manager.revoke(hass_owner_user.id, created.grant_id))[
        "audit_degraded"
    ]
    assert calls == []


@pytest.mark.parametrize(
    "payload", [{"offset": True}, {"limit": 51}, {"service": "light.turn_on"}]
)
async def test_strict_api_input(owner_client, payload):
    result = await command(owner_client, "list", payload)
    assert result["error"]["code"] == "invalid_format"
