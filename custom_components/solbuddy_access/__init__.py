"""SOLBUDDY Access owner management and explicitly enabled guest access."""

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError

from . import const, guest_api
from .api import register
from .audit import AuditStore
from .auth import GuestAuthenticator
from .const import DOMAIN
from .executor import LightExecutor
from .grants import GrantManager
from .storage import GrantStorage, StorageUnavailable


@dataclass(slots=True)
class RuntimeData:
    storage: GrantStorage
    authenticator: GuestAuthenticator
    manager: GrantManager
    guest_origin: str = ""


type SolbuddyConfigEntry = ConfigEntry[RuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: SolbuddyConfigEntry) -> bool:
    """Load existing security state; never recreate missing state on startup."""
    try:
        if set(entry.data) not in ({"storage_id"}, {"storage_id", "audit_initialized"}):
            raise ValueError("Invalid entry")
        if (
            "audit_initialized" in entry.data
            and entry.data["audit_initialized"] is not True
        ):
            raise ValueError("Invalid audit marker")
        storage = GrantStorage(hass, entry.data["storage_id"])
        await storage.async_load()
    except ValueError, StorageUnavailable:
        raise ConfigEntryError("SOLBUDDY Access storage is unavailable") from None
    audit = AuditStore(hass, entry.data["storage_id"])
    try:
        await audit.load(initialize="audit_initialized" not in entry.data)
    except StorageUnavailable:
        # Owners can still inspect/revoke grants when the audit store is unhealthy.
        pass
    else:
        if "audit_initialized" not in entry.data:
            hass.config_entries.async_update_entry(
                entry, data=dict(entry.data) | {"audit_initialized": True}
            )
    manager = GrantManager(hass, storage, audit, LightExecutor(hass))
    enabled = entry.options.get("guest_enabled", False) is True
    origin = ""
    if enabled:
        try:
            origin = guest_api.validate_origin(entry.options.get("guest_origin"))
        except ValueError:
            raise ConfigEntryError("Invalid guest HTTPS origin") from None
    authenticator = GuestAuthenticator(
        manager,
        enabled=enabled and const.GUEST_TRANSPORT_VERIFIED,
    )
    entry.runtime_data = RuntimeData(storage, authenticator, manager, origin)
    hass.data[DOMAIN] = entry.runtime_data
    register(hass)
    if authenticator.enabled:
        guest_api.register(hass)
    entry.async_on_unload(storage.close)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SolbuddyConfigEntry) -> bool:
    """Block new work and drain bounded internal execution before unloading."""
    await entry.runtime_data.manager.close()
    hass.data.pop(DOMAIN, None)
    return True
