"""SOLBUDDY Access owner management and explicitly enabled guest access."""

from collections.abc import Mapping
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import const, guest_api
from .api import register
from .audit import AuditStore
from .auth import GuestAuthenticator
from .const import DOMAIN
from .eligibility import Eligibility, load_provider_config
from .executor import LightExecutor
from .grants import GrantManager
from .storage import GrantStorage, StorageUnavailable
from .transport import TransportPolicy, async_transport_policy


@dataclass(slots=True)
class RuntimeData:
    storage: GrantStorage
    authenticator: GuestAuthenticator
    manager: GrantManager
    guest_origin: str = ""
    transport_policy: TransportPolicy | None = None
    transport_options: Mapping | None = None


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
    try:
        policy = await async_transport_policy(hass, entry.options)
    except ValueError:
        raise ConfigEntryError("Invalid guest transport options") from None
    wallet_enabled = enabled and entry.options.get("wallet_enabled", False) is True
    eligibility = None
    if wallet_enabled:
        try:
            rpc, key = await hass.async_add_executor_job(
                load_provider_config, hass.config.config_dir
            )
            eligibility = Eligibility(async_get_clientsession(hass), rpc, key)
        except ValueError:
            raise ConfigEntryError(
                "Wallet provider configuration unavailable"
            ) from None
    authenticator = GuestAuthenticator(
        manager,
        enabled=enabled and const.GUEST_TRANSPORT_VERIFIED,
        wallet_enabled=wallet_enabled,
        eligibility=eligibility,
        installation_id=entry.data["storage_id"],
    )
    entry.runtime_data = RuntimeData(
        storage, authenticator, manager, policy.https_origin, policy, entry.options
    )
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
