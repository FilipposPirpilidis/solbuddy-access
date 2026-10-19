"""Reviewed single-light enrollment and fixed service dispatch.

HA and its integrations are trusted. Registry platform names alone do not
distinguish a physical light from a group, so check the loaded implementation.
"""

from homeassistant.components.light import brightness_supported
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .models import Action, LightPolicy, ValidationError
from .permissions import EntitySnapshot


class LightExecutor:
    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    def snapshot(self, entity_id: str) -> EntitySnapshot | None:
        """Return fresh evidence only for source-reviewed Hue v2 physical lights."""
        registry = er.async_get(self.hass).async_get(entity_id)
        component = self.hass.data.get("light")
        entity = component.get_entity(entity_id) if component else None
        state = self.hass.states.get(entity_id)
        if registry is None or entity is None or state is None:
            return None
        if (
            registry.platform != "hue"
            or not entity_id.startswith("light.")
            or registry.disabled_by is not None
            or registry.config_entry_id is None
            or registry.device_id is None
            or type(entity).__module__ != "homeassistant.components.hue.v2.light"
            or type(entity).__name__ != "HueLight"
            or entity.unique_id != registry.unique_id
        ):
            return None
        entry = self.hass.config_entries.async_get_entry(registry.config_entry_id)
        device = dr.async_get(self.hass).async_get(registry.device_id)
        physical = getattr(entity, "device", None)
        if (
            entry is None
            or entry.domain != "hue"
            or entry.state is not ConfigEntryState.LOADED
            or device is None
            or device.disabled_by is not None
            or registry.config_entry_id != device.config_entry_id
            or physical is None
            or ("hue", physical.id) not in device.identifiers
        ):
            return None
        return EntitySnapshot(
            entity_id,
            registry.id,
            registry.config_entry_id,
            reviewed_physical_device=True,
            available=entity.available is True
            and state.state not in {"unavailable", "unknown"},
            supports_brightness=brightness_supported(entity.supported_color_modes),
            device_id=registry.device_id,
            unique_id=registry.unique_id,
        )

    def enroll(self, value: object) -> LightPolicy:
        """Resolve identity on the server; callers supply only policy choices."""
        if (
            type(value) is not dict
            or set(value)
            - {
                "entity_id",
                "actions",
                "brightness_min",
                "brightness_max",
                "turn_on_brightness",
            }
            or not {"entity_id", "actions"} <= set(value)
        ):
            raise ValidationError("Invalid policy fields")
        entity_id = value["entity_id"]
        if type(entity_id) is not str:
            raise ValidationError("Invalid entity")
        evidence = self.snapshot(entity_id)
        if evidence is None or not evidence.available:
            raise ValidationError("Entity is not an eligible physical light")
        policy = LightPolicy.from_dict(
            {
                "entity_id": entity_id,
                "registry_id": evidence.registry_id,
                "config_entry_id": evidence.config_entry_id,
                "actions": value["actions"],
                "brightness_min": value.get("brightness_min"),
                "brightness_max": value.get("brightness_max"),
                "turn_on_brightness": value.get("turn_on_brightness"),
                "device_id": evidence.device_id,
                "unique_id": evidence.unique_id,
            }
        )
        if policy.brightness_min is not None and not evidence.supports_brightness:
            raise ValidationError("Brightness unsupported")
        return policy

    async def dispatch(
        self, policy: LightPolicy, action: str, parameters: dict
    ) -> None:
        """Private application-service adapter; never accept a caller service name."""
        selected = Action(action)
        service = "turn_off" if selected is Action.TURN_OFF else "turn_on"
        data = {"entity_id": policy.entity_id}
        if selected is Action.SET_BRIGHTNESS:
            data["brightness"] = parameters["brightness"]
        elif selected is Action.TURN_ON and policy.turn_on_brightness is not None:
            data["brightness"] = policy.turn_on_brightness
        await self.hass.services.async_call(
            "light",
            service,
            data,
            blocking=True,
            context=Context(),
        )
