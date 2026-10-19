"""Pure policy preview only: no authentication, HA calls, or execution tickets."""

from dataclasses import dataclass
from datetime import datetime

from .models import Action, Grant, GrantStatus, ValidationError


@dataclass(frozen=True, slots=True)
class EntitySnapshot:
    """Fresh registry/device evidence supplied by the reviewed HA adapter."""

    entity_id: str
    registry_id: str
    config_entry_id: str
    reviewed_physical_device: bool = False
    available: bool = False
    supports_brightness: bool = False
    device_id: str | None = None
    unique_id: str | None = None


@dataclass(frozen=True, slots=True)
class Decision:
    allowed: bool
    reason: str


def evaluate(
    grant: Grant,
    *,
    now: datetime,
    entity_id: object,
    action: object,
    parameters: object,
    entity: EntitySnapshot | None,
    storage_healthy: bool,
) -> Decision:
    """Evaluate a policy, never grant guest execution authority.

    Authentication and fresh dispatch checks are separate later-phase gates.
    """
    if storage_healthy is not True:
        return Decision(False, "storage_unavailable")
    try:
        status = grant.status(now)
    except ValidationError, OverflowError:
        return Decision(False, "invalid_time")
    if status is not GrantStatus.ACTIVE:
        return Decision(False, f"grant_{status.value}")
    if (
        type(entity_id) is not str
        or type(action) is not str
        or type(parameters) is not dict
    ):
        return Decision(False, "invalid_request")
    policy = next((p for p in grant.policies if p.entity_id == entity_id), None)
    if policy is None:
        return Decision(False, "entity_denied")
    try:
        selected = Action(action)
    except ValueError:
        return Decision(False, "action_denied")
    if selected not in policy.actions:
        return Decision(False, "action_denied")
    if (
        entity is None
        or entity.reviewed_physical_device is not True
        or entity.available is not True
        or entity.entity_id != policy.entity_id
        or entity.registry_id != policy.registry_id
        or entity.config_entry_id != policy.config_entry_id
        or entity.device_id != policy.device_id
        or entity.unique_id != policy.unique_id
    ):
        return Decision(False, "entity_unverified")
    if policy.brightness_min is not None and entity.supports_brightness is not True:
        return Decision(False, "capability_denied")
    if selected is Action.SET_BRIGHTNESS:
        if set(parameters) != {"brightness"}:
            return Decision(False, "invalid_parameters")
        value = parameters["brightness"]
        if (
            type(value) is not int
            or policy.brightness_min is None
            or policy.brightness_max is None
            or not policy.brightness_min <= value <= policy.brightness_max
        ):
            return Decision(False, "brightness_denied")
    elif parameters:
        return Decision(False, "invalid_parameters")
    return Decision(True, "policy_allows")
