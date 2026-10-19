"""Immutable, strictly validated light grants with persistent device bindings.

Climate policies are deliberately rejected until their adapter is implemented.
All persistence input passes through the same constructors as new policies.
"""

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID, uuid4

from .const import MAX_DURATION_DAYS, MAX_ENTITIES


class ValidationError(ValueError):
    """Input violates the grant schema; messages never echo input."""


class Action(StrEnum):
    TURN_ON = "turn_on"
    TURN_OFF = "turn_off"
    SET_BRIGHTNESS = "set_brightness"


class GrantStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"


def require_text(value: object, maximum: int = 256) -> str:
    if (
        type(value) is not str
        or not 1 <= len(value) <= maximum
        or value != value.strip()
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise ValidationError("Invalid text")
    return value


def require_time(value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValidationError("Timezone-aware timestamp required")
    if value.utcoffset() is None:
        raise ValidationError("Timezone-aware timestamp required")
    return value.astimezone(UTC)


def parse_time(value: object) -> datetime:
    require_text(value, 64)
    try:
        return require_time(datetime.fromisoformat(value))
    except ValueError as err:
        raise ValidationError("Invalid timestamp") from err


def require_keys(value: object, keys: set[str]) -> dict:
    if type(value) is not dict or set(value) != keys:
        raise ValidationError("Invalid object fields")
    return value


@dataclass(frozen=True, slots=True)
class LightPolicy:
    entity_id: str
    registry_id: str
    config_entry_id: str
    actions: frozenset[Action]
    brightness_min: int | None = None
    brightness_max: int | None = None
    turn_on_brightness: int | None = None
    device_id: str | None = None
    unique_id: str | None = None

    def __post_init__(self) -> None:
        require_text(self.entity_id)
        if re.fullmatch(r"light\.[a-z0-9_]+", self.entity_id) is None:
            raise ValidationError("Only exact light entities are supported")
        require_text(self.registry_id)
        require_text(self.config_entry_id)
        if (self.device_id is None) != (self.unique_id is None):
            raise ValidationError("Incomplete device binding")
        if self.device_id is not None:
            require_text(self.device_id)
            require_text(self.unique_id)
        if (
            type(self.actions) is not frozenset
            or not self.actions
            or any(type(action) is not Action for action in self.actions)
        ):
            raise ValidationError("Explicit supported actions required")
        values = (self.brightness_min, self.brightness_max, self.turn_on_brightness)
        if any(value is not None for value in values):
            if any(type(value) is not int or not 1 <= value <= 255 for value in values):
                raise ValidationError("Invalid brightness limits")
            if (
                not self.brightness_min
                <= self.turn_on_brightness
                <= self.brightness_max
            ):
                raise ValidationError("Invalid turn-on brightness")
        elif Action.SET_BRIGHTNESS in self.actions:
            raise ValidationError("Brightness action requires explicit limits")

    def to_dict(self) -> dict:
        return {
            "entity_id": self.entity_id,
            "registry_id": self.registry_id,
            "config_entry_id": self.config_entry_id,
            "actions": sorted(action.value for action in self.actions),
            "brightness_min": self.brightness_min,
            "brightness_max": self.brightness_max,
            "turn_on_brightness": self.turn_on_brightness,
            "device_id": self.device_id,
            "unique_id": self.unique_id,
        }

    @classmethod
    def from_dict(cls, value: object) -> LightPolicy:
        data = require_keys(
            value,
            {
                "entity_id",
                "registry_id",
                "config_entry_id",
                "actions",
                "brightness_min",
                "brightness_max",
                "turn_on_brightness",
                "device_id",
                "unique_id",
            },
        )
        actions = data["actions"]
        if type(actions) is not list or not actions or len(actions) > len(Action):
            raise ValidationError("Invalid action list")
        if any(type(action) is not str for action in actions):
            raise ValidationError("Invalid action type")
        if len(set(actions)) != len(actions):
            raise ValidationError("Duplicate actions")
        try:
            parsed = frozenset(Action(action) for action in actions)
        except ValueError as err:
            raise ValidationError("Unsupported action") from err
        return cls(**(data | {"actions": parsed}))


@dataclass(frozen=True, slots=True)
class Grant:
    grant_id: str
    guest_display_name: str
    created_by: str
    created_at: datetime
    starts_at: datetime
    expires_at: datetime
    policies: tuple[LightPolicy, ...]
    guest_identifier: str | None = None
    revoked_at: datetime | None = None
    revoked_by: str | None = None

    def __post_init__(self) -> None:
        require_text(self.grant_id)
        try:
            identifier = UUID(self.grant_id)
        except ValueError as err:
            raise ValidationError("Invalid grant ID") from err
        if identifier.version != 4 or str(identifier) != self.grant_id:
            raise ValidationError("Canonical UUID4 required")
        require_text(self.guest_display_name, 100)
        require_text(self.created_by)
        if self.guest_identifier is not None:
            require_text(self.guest_identifier)
            if ":" not in self.guest_identifier:
                raise ValidationError("Guest identifier must be namespaced")
        for field in ("created_at", "starts_at", "expires_at"):
            object.__setattr__(self, field, require_time(getattr(self, field)))
        if (
            not timedelta(0)
            < self.expires_at - self.starts_at
            <= timedelta(days=MAX_DURATION_DAYS)
        ):
            raise ValidationError("Invalid grant duration")
        if self.expires_at <= self.created_at:
            raise ValidationError("Grant must expire after creation")
        if (
            type(self.policies) is not tuple
            or not 1 <= len(self.policies) <= MAX_ENTITIES
        ):
            raise ValidationError("Invalid policy collection")
        if any(type(policy) is not LightPolicy for policy in self.policies):
            raise ValidationError("Unsupported policy")
        for field in ("entity_id", "registry_id"):
            if len({getattr(policy, field) for policy in self.policies}) != len(
                self.policies
            ):
                raise ValidationError("Duplicate entity binding")
        if (self.revoked_at is None) != (self.revoked_by is None):
            raise ValidationError("Incomplete revocation")
        if self.revoked_at is not None:
            object.__setattr__(self, "revoked_at", require_time(self.revoked_at))
            require_text(self.revoked_by)
            if self.revoked_at < self.created_at:
                raise ValidationError("Revocation precedes creation")

    @classmethod
    def create(
        cls,
        *,
        guest_display_name: str,
        created_by: str,
        now: datetime,
        starts_at: datetime,
        expires_at: datetime,
        policies: tuple[LightPolicy, ...],
        guest_identifier: str | None = None,
    ) -> Grant:
        return cls(
            str(uuid4()),
            guest_display_name,
            created_by,
            now,
            starts_at,
            expires_at,
            policies,
            guest_identifier,
        )

    def status(self, now: datetime) -> GrantStatus:
        now = require_time(now)
        if self.revoked_at is not None:
            return GrantStatus.REVOKED
        if now >= self.expires_at:
            return GrantStatus.EXPIRED
        if now < self.starts_at:
            return GrantStatus.PENDING
        return GrantStatus.ACTIVE

    def to_dict(self) -> dict:
        return {
            "schema_version": 2,
            "grant_id": self.grant_id,
            "guest_display_name": self.guest_display_name,
            "guest_identifier": self.guest_identifier,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat(),
            "starts_at": self.starts_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "revoked_at": self.revoked_at.isoformat() if self.revoked_at else None,
            "revoked_by": self.revoked_by,
            "policies": [policy.to_dict() for policy in self.policies],
        }

    @classmethod
    def from_dict(cls, value: object) -> Grant:
        data = require_keys(
            value,
            {
                "schema_version",
                "grant_id",
                "guest_display_name",
                "guest_identifier",
                "created_by",
                "created_at",
                "starts_at",
                "expires_at",
                "revoked_at",
                "revoked_by",
                "policies",
            },
        )
        if type(data["schema_version"]) is not int or data["schema_version"] not in (
            1,
            2,
        ):
            raise ValidationError("Unsupported grant schema")
        if type(data["policies"]) is not list or len(data["policies"]) > MAX_ENTITIES:
            raise ValidationError("Invalid policies")
        fields = {key: val for key, val in data.items() if key != "schema_version"}
        for field in ("created_at", "starts_at", "expires_at"):
            fields[field] = parse_time(fields[field])
        if fields["revoked_at"] is not None:
            fields["revoked_at"] = parse_time(fields["revoked_at"])
        if data["schema_version"] == 1:
            # Legacy policies remain inspectable/revocable, but cannot execute
            # until replaced with a freshly enrolled device binding.
            legacy = []
            for policy in fields["policies"]:
                if type(policy) is not dict or {"device_id", "unique_id"} & set(policy):
                    raise ValidationError("Invalid legacy binding")
                legacy.append(policy | {"device_id": None, "unique_id": None})
            fields["policies"] = legacy
        fields["policies"] = tuple(LightPolicy.from_dict(p) for p in fields["policies"])
        return cls(**fields)
