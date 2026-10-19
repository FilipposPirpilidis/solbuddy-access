"""Actual HA config flow and config-entry setup/unload."""

from unittest.mock import patch

import pytest
from aiohttp.test_utils import make_mocked_request
from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from homeassistant.helpers.http import KEY_AUTHENTICATED, current_request
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.solbuddy_access.auth import GuestAccessDisabled
from custom_components.solbuddy_access.const import DOMAIN
from custom_components.solbuddy_access.storage import StorageUnavailable


@pytest.fixture
def owner_request(hass_owner_user):
    request = make_mocked_request("POST", "/api/config/config_entries/flow")
    request[KEY_AUTHENTICATED] = True
    request["hass_user"] = hass_owner_user
    token = current_request.set(request)
    yield request
    current_request.reset(token)


async def test_setup_singleton_and_unload(hass, owner_request):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    with patch("homeassistant.core.ServiceRegistry.async_register") as register_service:
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    entry = result["result"]
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.storage.grants == ()
    register_service.assert_not_called()
    with pytest.raises(GuestAccessDisabled):
        await entry.runtime_data.authenticator.authenticate("synthetic-token")
    duplicate = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert duplicate["type"] is FlowResultType.ABORT
    assert duplicate["reason"] == "single_instance_allowed"
    runtime = entry.runtime_data
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert not runtime.storage.healthy
    assert await hass.config_entries.async_setup(entry.entry_id)
    assert entry.runtime_data.storage.healthy


async def test_storage_failure_is_form_error(hass, owner_request):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    with patch(
        "custom_components.solbuddy_access.config_flow.GrantStorage.async_initialize",
        side_effect=StorageUnavailable,
    ):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "storage_unavailable"}
    assert not hass.config_entries.async_entries(DOMAIN)


async def test_setup_rejects_missing_identity(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER, "user_id": "forged-owner"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "owner_required"


async def test_setup_rejects_admin(hass, owner_request, hass_admin_user):
    owner_request["hass_user"] = hass_admin_user
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["reason"] == "owner_required"


async def test_owner_status_rechecked_at_confirmation(hass, owner_request):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    with patch("homeassistant.auth.AuthManager.async_get_user", return_value=None):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["reason"] == "owner_required"
    assert not hass.config_entries.async_entries(DOMAIN)


async def test_no_guest_routes(hass, hass_client, owner_request):
    from homeassistant.setup import async_setup_component

    assert await async_setup_component(hass, "http", {"http": {}})
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    await hass.config_entries.flow.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()
    client = await hass_client()
    for operation in (
        "session",
        "session/renew",
        "check",
        "execute",
        "wallet/challenge",
        "wallet/verify",
        "wallet/renew-challenge",
        "wallet/renew",
    ):
        response = await client.post(f"/api/solbuddy_access/v1/{operation}", json={})
        assert response.status == 404
    response = await client.get("/api/solbuddy_access/v1/permissions")
    assert response.status == 404


async def test_missing_storage_blocks_existing_entry(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"storage_id": "75684c28-217b-4a68-bf89-b63dc05f43bb"},
        unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_ERROR


@pytest.mark.parametrize("credential", [None, "", "fake", {"is_admin": True}])
async def test_guest_auth_always_disabled(credential):
    from custom_components.solbuddy_access.auth import GuestAuthenticator

    with pytest.raises(GuestAccessDisabled):
        await GuestAuthenticator().authenticate(credential)


@pytest.mark.parametrize("gate", [False, True])
@pytest.mark.parametrize("wallet", [False, True])
async def test_guest_options_security_gate(
    hass, owner_request, monkeypatch, gate, wallet
):
    from custom_components.solbuddy_access import const

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()
    entry = result["result"]
    assert not entry.runtime_data.authenticator.enabled
    assert not entry.runtime_data.authenticator.wallet_enabled
    monkeypatch.setattr(const, "GUEST_TRANSPORT_VERIFIED", gate)
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    assert {key.schema for key in flow["data_schema"].schema} == {
        "guest_enabled",
        "wallet_enabled",
    }
    result = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"guest_enabled": True, "wallet_enabled": wallet}
    )
    if not gate:
        assert result["reason"] == "security_gate_closed"
        return
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.runtime_data.authenticator.enabled
    assert entry.runtime_data.authenticator.wallet_enabled is wallet
    assert entry.options["connection_mode"] == "ha"
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    await hass.config_entries.options.async_configure(
        flow["flow_id"], {"guest_enabled": False, "wallet_enabled": True}
    )
    await hass.async_block_till_done()
    assert not entry.runtime_data.authenticator.enabled
    assert not entry.runtime_data.authenticator.wallet_enabled


async def test_guest_options_reject_admin(hass, owner_request, hass_admin_user):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()
    owner_request["hass_user"] = hass_admin_user
    result = await hass.config_entries.options.async_init(result["result"].entry_id)
    assert result["reason"] == "owner_required"


async def test_options_reject_removed_proxy_fields(hass, owner_request):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()
    flow = await hass.config_entries.options.async_init(result["result"].entry_id)
    with pytest.raises(InvalidData):
        await hass.config_entries.options.async_configure(
            flow["flow_id"],
            {"guest_enabled": True, "https_proxy_ips": "192.168.68.112"},
        )
