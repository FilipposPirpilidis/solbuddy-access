"""Local bundled wallet pages; no credentials in URLs or browser storage."""

from pathlib import Path

from aiohttp import web
from homeassistant.helpers.http import HomeAssistantView

from .const import DOMAIN
from .transport import TransportPolicy, async_transport_policy

ASSETS = {
    "ui": ("wallet.html", "text/html"),
    "owner-ui": ("wallet.html", "text/html"),
    "client.js": ("client.js", "application/javascript"),
    "connectors.js": ("connectors.js", "application/javascript"),
    "wallet.css": ("wallet.css", "text/css"),
}


class WalletAsset(HomeAssistantView):
    requires_auth = False
    cors_allowed = False

    def __init__(self, hass, name):
        self.hass, self.asset = hass, name
        self.url = "/api/solbuddy_access/v1/wallet/" + name
        self.name = "solbuddy:wallet:asset:" + name

    async def get(self, request):
        runtime = self.hass.data.get(DOMAIN)
        if (
            runtime is None
            or not runtime.authenticator.enabled
            or not runtime.authenticator.wallet_enabled
        ):
            return web.Response(status=404)
        try:
            policy = runtime.transport_policy or TransportPolicy(
                https_origin=runtime.guest_origin
            )
            if runtime.transport_options is not None:
                policy = await async_transport_policy(
                    self.hass, runtime.transport_options
                )
            TransportPolicy(
                https_origin=policy.https_origin, proxy_ips=policy.proxy_ips
            ).check(request, self.hass.http.trusted_proxies)
        except Exception:
            return web.Response(status=403)
        filename, content_type = ASSETS[self.asset]
        content = await self.hass.async_add_executor_job(
            (Path(__file__).parent / "www" / filename).read_text
        )
        return web.Response(
            text=content,
            content_type=content_type,
            headers={
                "Cache-Control": "no-store",
                "Referrer-Policy": "no-referrer",
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": (
                    "default-src 'none'; script-src 'self'; style-src 'self'; "
                    "connect-src 'self'; frame-ancestors 'none'; "
                    "base-uri 'none'; form-action 'none'"
                ),
            },
        )


def register_ui(hass):
    for name in ASSETS:
        hass.http.register_view(WalletAsset(hass, name))
