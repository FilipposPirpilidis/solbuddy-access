"""SOLBUDDY Access owner management; guest endpoints remain absent."""

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError

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
    entry.runtime_data = RuntimeData(storage, GuestAuthenticator(), manager)
    hass.data[DOMAIN] = entry.runtime_data
    register(hass)
    entry.async_on_unload(storage.close)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SolbuddyConfigEntry) -> bool:
    """Block new work and drain bounded internal execution before unloading."""
    await entry.runtime_data.manager.close()
    hass.data.pop(DOMAIN, None)
    return True
