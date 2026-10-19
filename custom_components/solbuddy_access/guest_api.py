"""Owner-configured HTTP/HTTPS transport with a mandatory scoped authenticator."""

import asyncio
import json
import re

from aiohttp import web
from homeassistant.core import HomeAssistant
from homeassistant.helpers.http import HomeAssistantView

from . import const
from .auth import AuthError, GuestAccessDisabled
from .grants import AccessDenied
from .models import ValidationError
from .storage import StorageUnavailable
from .transport import TransportPolicy

BASE = "/api/solbuddy_access/v1"
HEADERS = {
    "Cache-Control": "no-store",
    "Pragma": "no-cache",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


def credential(request: web.Request, scheme: str) -> str:
    values = request.headers.getall("Authorization", [])
    if len(values) != 1 or len(values[0]) > 128:
        raise AuthError()
    prefix = scheme + " "
    if not values[0].startswith(prefix):
        raise AuthError()
    return values[0][len(prefix) :]


def sequence(request: web.Request) -> int:
    values = request.headers.getall("X-Solbuddy-Sequence", [])
    if len(values) != 1 or re.fullmatch(r"[1-9][0-9]{0,9}", values[0]) is None:
        raise AuthError(409, "sequence_conflict")
    return int(values[0])


def _pairs(values: list[tuple]) -> dict:
    result = {}
    for key, value in values:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _constant(value: str):
    raise ValueError("Nonfinite JSON number")


async def body(request: web.Request) -> dict:
    if request.headers.get("Content-Encoding", "identity") != "identity":
        raise AuthError(400, "encoding_denied")
    if request.content_length is not None and request.content_length > 8192:
        raise AuthError(413, "body_too_large")
    async with asyncio.timeout(5):
        raw = bytearray()
        async for chunk in request.content.iter_chunked(1024):
            raw.extend(chunk)
            if len(raw) > 8192:
                raise AuthError(413, "body_too_large")
    if not raw:
        return {}
    if request.content_type != "application/json":
        raise AuthError(400, "json_required")
    parsed = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_constant)
    if type(parsed) is not dict:
        raise AuthError(400, "invalid_request")
    return parsed


def response(data: dict, status: int = 200) -> web.Response:
    return web.json_response(data, status=status, headers=HEADERS)


class GuestView(HomeAssistantView):
    # Opt out ONLY of HA-token authentication; _handle enforces scoped credentials.
    requires_auth = False
    cors_allowed = False

    def __init__(self, hass: HomeAssistant, operation: str) -> None:
        self.hass = hass
        self.operation = operation
        self.url = f"{BASE}/{operation}"
        self.name = "api:solbuddy_access:" + operation.replace("/", ":")
        if operation == "invitations":
            self.requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        return await self._handle(request)

    async def post(self, request: web.Request) -> web.Response:
        return await self._handle(request)

    async def _handle(self, request: web.Request) -> web.Response:
        try:
            runtime = self.hass.data.get(const.DOMAIN)
            if runtime is None or not runtime.authenticator.enabled:
                return response({"error": "not_found"}, 404)
            auth = runtime.authenticator
            policy = runtime.transport_policy or TransportPolicy(
                https_origin=runtime.guest_origin
            )
            source = policy.check(request, self.hass.http.trusted_proxies)
            auth.limit_source(source)
            expected = "GET" if self.operation == "permissions" else "POST"
            if request.method != expected:
                raise AuthError(405, "method_not_allowed")
            if self.operation == "invitations":
                user = request.get("hass_user")
                if user is None:
                    raise AuthError()
                await runtime.manager.require_owner(user.id)
                data = await body(request)
                if set(data) != {"grant_id"} or type(data["grant_id"]) is not str:
                    raise AuthError(400, "invalid_request")
                return response(await auth.issue(user.id, data["grant_id"]))
            if self.operation == "session":
                token = credential(request, "SolbuddyInvite")
                # Authenticate before reading the bounded body; no anonymous parsing.
                auth._lookup(token, "sbai_", auth._invitations)
                if await body(request):
                    raise AuthError(400, "invalid_request")
                return response(await auth.exchange(token))
            token = credential(request, "SolbuddySession")
            async with auth.request(token, sequence(request)) as session:
                data = await body(request)
                auth.assert_live(session)
                if self.operation == "session/renew":
                    if data:
                        raise AuthError(400, "invalid_request")
                    return response(await auth.renew(session))
                if self.operation == "permissions":
                    if data:
                        raise AuthError(400, "invalid_request")
                    grant = runtime.manager.get(session.grant_id)
                    return response(
                        {
                            "expires_at": grant.expires_at.isoformat(),
                            "policies": [
                                {
                                    k: v
                                    for k, v in p.to_dict().items()
                                    if k
                                    in {
                                        "entity_id",
                                        "actions",
                                        "brightness_min",
                                        "brightness_max",
                                        "turn_on_brightness",
                                    }
                                }
                                for p in grant.policies
                            ],
                        }
                    )
                if self.operation == "check":
                    decision = runtime.manager.check(session.grant_id, data)
                    return response(
                        {"allowed": decision.allowed}, 200 if decision.allowed else 403
                    )
                if self.operation == "execute":
                    result = await runtime.manager.execute(
                        session.grant_id,
                        data,
                        authorize=lambda: auth.assert_live(session),
                    )
                    return response(
                        {"outcome": result["outcome"]},
                        403 if result["outcome"] == "denied" else 200,
                    )
                raise AuthError(404, "not_found")
        except AuthError as err:
            return response({"error": err.code}, err.status)
        except AccessDenied:
            return response({"error": "not_allowed"}, 403)
        except GuestAccessDisabled, StorageUnavailable, TimeoutError:
            return response({"error": "unavailable"}, 503)
        except ValidationError, ValueError, TypeError, KeyError, RecursionError:
            return response({"error": "invalid_request"}, 400)
        except Exception:
            # Never forward raw body/header/exception values into HA logging.
            return response({"error": "unavailable"}, 503)


def register(hass: HomeAssistant) -> None:
    if not const.GUEST_TRANSPORT_VERIFIED:
        raise GuestAccessDisabled("Guest transport security gate is closed")
    if hass.data.get("solbuddy_access_guest_registered"):
        return
    for operation in (
        "invitations",
        "session",
        "session/renew",
        "permissions",
        "check",
        "execute",
    ):
        hass.http.register_view(GuestView(hass, operation))
    hass.data["solbuddy_access_guest_registered"] = True
