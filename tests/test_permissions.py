"""Default-deny previews; no device executor exists in Phase 1."""

from dataclasses import replace
from datetime import timedelta

import pytest

from custom_components.solbuddy_access.models import Action
from custom_components.solbuddy_access.permissions import EntitySnapshot, evaluate


@pytest.fixture
def request_kwargs(now):
    return {
        "now": now,
        "entity_id": "light.guest_room",
        "action": "turn_on",
        "parameters": {},
        "storage_healthy": True,
        "entity": EntitySnapshot(
            "light.guest_room",
            "registry-1",
            "integration-1",
            reviewed_physical_device=True,
            available=True,
            supports_brightness=True,
        ),
    }


def test_allowed_actions(grant, request_kwargs):
    for action, parameters in [
        ("turn_on", {}),
        ("turn_off", {}),
        ("set_brightness", {"brightness": 20}),
        ("set_brightness", {"brightness": 180}),
    ]:
        result = evaluate(
            grant, **(request_kwargs | {"action": action, "parameters": parameters})
        )
        assert result.allowed


@pytest.mark.parametrize(
    "changes",
    [
        {"entity_id": "light.other"},
        {"entity_id": "lock.front_door", "action": "unlock"},
        {"entity_id": "camera.entry"},
        {"entity_id": "alarm_control_panel.home"},
        {"entity_id": "climate.room"},
        {"entity_id": ["light.guest_room"]},
        {"action": "toggle"},
        {"action": "homeassistant.turn_on"},
        {"action": "turn_on", "parameters": {"entity_id": "lock.front_door"}},
        {"parameters": {"transition": 0}},
        {"parameters": []},
        {"entity": None},
        {"storage_healthy": False},
        {"storage_healthy": 1},
    ],
)
def test_default_deny(grant, request_kwargs, changes):
    assert not evaluate(grant, **(request_kwargs | changes)).allowed


@pytest.mark.parametrize(
    "value", [0, 19, 181, 256, True, "100", 100.0, float("nan"), float("inf")]
)
def test_brightness_rejected(grant, request_kwargs, value):
    assert not evaluate(
        grant,
        **(
            request_kwargs
            | {
                "action": "set_brightness",
                "parameters": {"brightness": value},
            }
        ),
    ).allowed


@pytest.mark.parametrize(
    "changes",
    [
        {"reviewed_physical_device": False},
        {"available": False},
        {"supports_brightness": False},
        {"registry_id": "replacement"},
        {"config_entry_id": "replacement"},
        {"entity_id": "light.other"},
    ],
)
def test_binding_and_capability(grant, request_kwargs, changes):
    entity = replace(request_kwargs["entity"], **changes)
    assert not evaluate(grant, **(request_kwargs | {"entity": entity})).allowed


def test_pending_expired_revoked(grant, now, request_kwargs):
    for at in (now - timedelta(seconds=1), grant.expires_at):
        assert not evaluate(grant, **(request_kwargs | {"now": at})).allowed
    revoked = replace(grant, revoked_at=now, revoked_by="owner")
    assert not evaluate(revoked, **request_kwargs).allowed
    assert not evaluate(
        grant, **(request_kwargs | {"now": now.replace(tzinfo=None)})
    ).allowed


def test_unpermitted_action(grant, policy, request_kwargs):
    restricted = replace(
        grant, policies=(replace(policy, actions=frozenset({Action.TURN_OFF})),)
    )
    assert not evaluate(restricted, **request_kwargs).allowed
