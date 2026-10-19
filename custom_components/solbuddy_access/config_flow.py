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
from .guest_api import secure_request, validate_origin
from .storage import GrantStorage, StorageUnavailable


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
                if set(user_input) - {"guest_enabled", "guest_origin"}:
                    raise ValueError("Unexpected options")
                enabled = user_input.get("guest_enabled", False)
                if type(enabled) is not bool:
                    raise ValueError("Invalid enablement")
                origin = ""
                if enabled:
                    if not const.GUEST_TRANSPORT_VERIFIED:
                        return self.async_abort(reason="security_gate_closed")
                    origin = validate_origin(user_input.get("guest_origin"))
                    secure_request(request, origin)
            except ValueError, AuthError:
                errors["base"] = "invalid_https_origin"
            else:
                return self.async_create_entry(
                    title="", data={"guest_enabled": enabled, "guest_origin": origin}
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
                    vol.Optional(
                        "guest_origin",
                        default=self.config_entry.options.get("guest_origin", ""),
                    ): str,
                }
            ),
        )
