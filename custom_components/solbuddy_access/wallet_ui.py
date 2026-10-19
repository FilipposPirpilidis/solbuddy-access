"""Local bundled wallet pages; no credentials in URLs or browser storage."""

from pathlib import Path

from aiohttp import web
from homeassistant.helpers.http import HomeAssistantView

from .const import DOMAIN

ASSETS = {
    "ui": ("wallet.html", "text/html"),
    "owner-ui": ("wallet.html", "text/html"),
    "owner-panel.js": ("owner-panel.js", "application/javascript"),
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
        if runtime is None:
            return web.Response(status=404)
        if self.asset == "owner-ui":
            return web.Response(
                status=302,
                headers={"Location": "/solbuddy-access", "Cache-Control": "no-store"},
            )
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


async def register_panel(hass):
    from homeassistant.components.panel_custom import async_register_panel

    await async_register_panel(
        hass,
        frontend_url_path="solbuddy-access",
        webcomponent_name="solbuddy-owner-panel",
        sidebar_title="SOLBUDDY Access",
        sidebar_icon="mdi:account-key",
        require_admin=True,
        module_url="/api/solbuddy_access/v1/wallet/owner-panel.js",
    )
