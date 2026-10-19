"""Singleton native setup; this flow never grants guest permissions."""

from uuid import uuid4

import probatio as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.core import callback
from homeassistant.helpers.http import KEY_AUTHENTICATED, current_request

from . import const
from .auth import AuthError
from .const import DOMAIN
from .storage import GrantStorage, StorageUnavailable
from .transport import LocalNetworkUnavailable, TransportPolicy, async_transport_policy


class SolbuddyConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlowWithReload:
        return SolbuddyOptionsFlow()

    async def async_step_user(self, user_input: dict | None = None) -> ConfigFlowResult:
        request = current_request.get()
        if (
            request is None
            or request.get(KEY_AUTHENTICATED) is not True
            or (request_user := request.get("hass_user")) is None
            or (user := await self.hass.auth.async_get_user(request_user.id)) is None
            or not user.is_active
            or not user.is_owner
            or user.system_generated
        ):
            return self.async_abort(reason="owner_required")
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input:
                return self.async_abort(reason="invalid_input")
            storage_id = str(uuid4())
            storage = GrantStorage(self.hass, storage_id)
            try:
                await storage.async_initialize()
            except StorageUnavailable:
                errors["base"] = "storage_unavailable"
            else:
                storage.close()
                return self.async_create_entry(
                    title="SOLBUDDY Access", data={"storage_id": storage_id}
                )
        return self.async_show_form(
            step_id="user", data_schema=vol.Schema({}), errors=errors
        )


class SolbuddyOptionsFlow(OptionsFlowWithReload):
    async def async_step_init(self, user_input: dict | None = None) -> ConfigFlowResult:
        request = current_request.get()
        if (
            request is None
            or request.get(KEY_AUTHENTICATED) is not True
            or (request_user := request.get("hass_user")) is None
            or (user := await self.hass.auth.async_get_user(request_user.id)) is None
            or not user.is_active
            or not user.is_owner
            or user.system_generated
        ):
            return self.async_abort(reason="owner_required")
        errors = {}
        if user_input is not None:
            try:
                policy = await async_transport_policy(
                    self.hass, user_input, require_local=True
                )
                enabled = user_input.get("guest_enabled", False)
                if enabled:
                    if not const.GUEST_TRANSPORT_VERIFIED:
                        return self.async_abort(reason="security_gate_closed")
                    policy.check(request, self.hass.http.trusted_proxies)
                    if user_input.get("wallet_enabled", False):
                        TransportPolicy(
                            https_origin=policy.https_origin, proxy_ips=policy.proxy_ips
                        ).check(request, self.hass.http.trusted_proxies)
            except LocalNetworkUnavailable:
                errors["base"] = "local_network_unavailable"
            except ValueError, AuthError:
                errors["base"] = "invalid_https_origin"
            else:
                return self.async_create_entry(
                    title="",
                    data={
                        "guest_enabled": enabled,
                        "wallet_enabled": enabled
                        and user_input.get("wallet_enabled", False),
                        "guest_origin": policy.https_origin,
                        "local_http_enabled": bool(policy.local_origin),
                        "local_http_origin": policy.local_origin,
                        "https_proxy_ips": ", ".join(map(str, policy.proxy_ips)),
                    },
                )
        return self.async_show_form(
            step_id="init",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "guest_enabled",
                        default=self.config_entry.options.get("guest_enabled", False),
                    ): bool,
                    vol.Required(
                        "wallet_enabled",
                        default=self.config_entry.options.get("wallet_enabled", False),
                    ): bool,
                    vol.Optional(
                        "guest_origin",
                        default=self.config_entry.options.get("guest_origin", ""),
                    ): str,
                    vol.Required(
                        "local_http_enabled",
                        default=self.config_entry.options.get(
                            "local_http_enabled", False
                        ),
                    ): bool,
                    vol.Optional(
                        "local_http_origin",
                        default=self.config_entry.options.get("local_http_origin", ""),
                    ): str,
                    vol.Optional(
                        "https_proxy_ips",
                        default=self.config_entry.options.get("https_proxy_ips", ""),
                    ): str,
                }
            ),
        )
