"""Owner-only WebSocket management. Deliberately no execute command."""

import json

import probatio as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN
from .grants import AccessDenied, GrantManager
from .models import ValidationError
from .storage import StorageUnavailable

COMMANDS = ("create", "list", "get", "revoke", "check")


@callback
def register(hass: HomeAssistant) -> None:
    """Register once; handlers always resolve the current runtime on reload."""
    marker = f"{DOMAIN}_api_registered"
    if hass.data.get(marker):
        return
    for operation in COMMANDS:
        websocket_api.async_register_command(hass, _handler(operation))
    hass.data[marker] = True


def _handler(operation: str):
    @websocket_api.websocket_command(
        {
            vol.Required("type"): f"{DOMAIN}/grants/{operation}",
            vol.Optional("payload", default=dict): dict,
        }
    )
    @websocket_api.async_response
    async def handle(hass, connection, message):
        try:
            runtime = hass.data.get(DOMAIN)
            if runtime is None or connection.user is None:
                raise AccessDenied("integration_unavailable")
            manager: GrantManager = runtime.manager
            owner_id = connection.user.id
            await manager.require_owner(owner_id)
            payload = message["payload"]
            if len(json.dumps(payload).encode()) > 8192:
                raise ValidationError("Payload too large")
            if operation == "create":
                result = manager.describe(await manager.create(owner_id, payload))
            elif operation == "list":
                if set(payload) - {"offset", "limit"}:
                    raise ValidationError("Invalid list fields")
                offset, limit = payload.get("offset", 0), payload.get("limit", 20)
                if (
                    type(offset) is not int
                    or not 0 <= offset <= 100
                    or type(limit) is not int
                    or not 1 <= limit <= 50
                ):
                    raise ValidationError("Invalid pagination")
                grants = manager.storage.grants
                result = {
                    "grants": [
                        {
                            "grant_id": g.grant_id,
                            "status": g.status(manager.now()).value,
                            "starts_at": g.starts_at.isoformat(),
                            "expires_at": g.expires_at.isoformat(),
                        }
                        for g in grants[offset : offset + limit]
                    ],
                    "next_offset": offset + limit
                    if offset + limit < len(grants)
                    else None,
                }
            elif operation == "get":
                _keys(payload, {"grant_id"})
                result = manager.describe(manager.get(payload["grant_id"]))
            elif operation == "revoke":
                _keys(payload, {"grant_id"})
                result = await manager.revoke(owner_id, payload["grant_id"])
            else:
                _keys(payload, {"grant_id", "entity_id", "action", "parameters"})
                decision = manager.check(
                    payload["grant_id"],
                    {k: v for k, v in payload.items() if k != "grant_id"},
                )
                result = {"allowed": decision.allowed, "reason": decision.reason}
            connection.send_result(message["id"], result)
        except AccessDenied:
            connection.send_error(
                message["id"], "not_allowed", "Owner access or security checks failed"
            )
        except ValidationError, ValueError, TypeError, KeyError:
            connection.send_error(message["id"], "invalid_format", "Invalid request")
        except StorageUnavailable, TimeoutError:
            connection.send_error(
                message["id"], "unavailable", "Security state unavailable"
            )
        except Exception:
            # Do not let HA's generic exception path log raw request/exception data.
            connection.send_error(message["id"], "unavailable", "Operation unavailable")

    return handle


def _keys(payload: dict, expected: set[str]) -> None:
    if set(payload) != expected:
        raise ValidationError("Invalid fields")
