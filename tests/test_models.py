"""Strict construction and persistence-input validation."""

from dataclasses import FrozenInstanceError, replace
from datetime import timedelta

import pytest

from custom_components.solbuddy_access.models import (
    Action,
    Grant,
    GrantStatus,
    LightPolicy,
    ValidationError,
)


def test_round_trip_and_immutable(grant):
    assert Grant.from_dict(grant.to_dict()) == grant
    with pytest.raises(FrozenInstanceError):
        grant.guest_display_name = "changed"


def test_time_boundaries(grant, now):
    assert grant.status(now - timedelta(microseconds=1)) is GrantStatus.PENDING
    assert grant.status(now) is GrantStatus.ACTIVE
    assert (
        grant.status(grant.expires_at - timedelta(microseconds=1)) is GrantStatus.ACTIVE
    )
    assert grant.status(grant.expires_at) is GrantStatus.EXPIRED
    revoked = replace(grant, revoked_at=now, revoked_by="owner")
    assert revoked.status(grant.expires_at) is GrantStatus.REVOKED


@pytest.mark.parametrize(
    "field,value",
    [
        ("entity_id", "lock.front_door"),
        ("entity_id", "climate.bedroom"),
        ("entity_id", "light.*"),
        ("entity_id", "light.one,light.two"),
        ("registry_id", ""),
        ("config_entry_id", None),
        ("actions", frozenset()),
        ("actions", frozenset({"turn_on"})),
        ("actions", [Action.TURN_ON]),
        ("brightness_min", True),
        ("brightness_min", 0),
        ("brightness_min", 200),
        ("brightness_max", 256),
        ("brightness_max", float("nan")),
        ("turn_on_brightness", 181),
        ("turn_on_brightness", None),
    ],
)
def test_invalid_policy(policy, field, value):
    with pytest.raises(ValidationError):
        replace(policy, **{field: value})


@pytest.mark.parametrize(
    "mutation",
    [
        {"status": "active"},
        {"schema_version": True},
        {"schema_version": 3},
        {"created_at": "2026-10-19T12:00:00"},
        {"starts_at": "invalid"},
        {"grant_id": "not-a-uuid"},
        {"guest_identifier": "unverified-wallet"},
        {"guest_display_name": ""},
        {"guest_display_name": "x" * 101},
        {"revoked_at": "2026-10-19T12:00:00Z"},
        {"policies": []},
    ],
)
def test_invalid_stored_grant(grant, mutation):
    with pytest.raises(ValidationError):
        Grant.from_dict(grant.to_dict() | mutation)


def test_invalid_dates_and_duplicates(grant, now, policy):
    for changes in (
        {"expires_at": now},
        {"expires_at": now + timedelta(days=31)},
        {"starts_at": now.replace(tzinfo=None)},
        {"policies": (policy, policy)},
        {"revoked_at": now - timedelta(seconds=1), "revoked_by": "owner"},
    ):
        with pytest.raises(ValidationError):
            replace(grant, **changes)


@pytest.mark.parametrize(
    "actions", [["turn_on", "turn_on"], ["unlock"], [True], "turn_on"]
)
def test_invalid_action_encoding(policy, actions):
    with pytest.raises(ValidationError):
        LightPolicy.from_dict(policy.to_dict() | {"actions": actions})


def test_brightness_requires_bounds(policy):
    with pytest.raises(ValidationError):
        replace(
            policy, brightness_min=None, brightness_max=None, turn_on_brightness=None
        )
    simple = replace(
        policy,
        actions=frozenset({Action.TURN_ON, Action.TURN_OFF}),
        brightness_min=None,
        brightness_max=None,
        turn_on_brightness=None,
    )
    assert LightPolicy.from_dict(simple.to_dict()) == simple
