"""Explicit local HTTP and single-hop trusted HTTPS proxy boundaries."""

import re
from dataclasses import dataclass
from ipaddress import ip_address, ip_interface, ip_network
from urllib.parse import urlsplit

from aiohttp import web
from hass_nabucasa import remote
from homeassistant.components.network import async_get_adapters
from homeassistant.exceptions import HomeAssistantError

from .auth import AuthError

LOCAL_RANGES = tuple(
    map(
        ip_network,
        (
            "10.0.0.0/8",
            "172.16.0.0/12",
            "192.168.0.0/16",
            "127.0.0.0/8",
            "fc00::/7",
            "::1/128",
        ),
    )
)
FIELDS = {
    "guest_enabled",
    "wallet_enabled",
    "guest_origin",
    "local_http_enabled",
    "local_http_origin",
    "local_http_networks",
    "https_proxy_ips",
}


def validate_origin(value: object, scheme: str = "https") -> str:
    if type(value) is not str or len(value) > 256:
        raise ValueError("Invalid origin")
    parts = urlsplit(value)
    if (
        parts.scheme != scheme
        or parts.path not in ("", "/")
        or parts.query
        or parts.fragment
        or parts.username
        or parts.password
        or not parts.hostname
        or parts.port == 0
        or not re.fullmatch(r"[a-zA-Z0-9.-]+(?::[0-9]{1,5})?", parts.netloc)
    ):
        raise ValueError("Invalid origin")
    return scheme + "://" + parts.netloc.lower()


def _items(value: object) -> list[str]:
    if type(value) is not str or len(value) > 2048:
        raise ValueError("Invalid network list")
    result = [item.strip() for item in value.split(",") if item.strip()]
    if len(result) > 16:
        raise ValueError("Too many networks")
    return result


@dataclass(frozen=True)
class TransportPolicy:
    https_origin: str = ""
    local_origin: str = ""
    local_networks: tuple = ()
    proxy_ips: tuple = ()

    @classmethod
    def from_options(
        cls, options, *, detected_networks: tuple | None = None
    ) -> TransportPolicy:
        if set(options) - FIELDS:
            raise ValueError("Unexpected options")
        for key in ("guest_enabled", "local_http_enabled", "wallet_enabled"):
            if type(options.get(key, False)) is not bool:
                raise ValueError("Invalid enablement")
        if not options.get("guest_enabled", False):
            return cls()
        https = options.get("guest_origin", "")
        https = validate_origin(https) if https else ""
        if options.get("wallet_enabled", False) and not https:
            raise ValueError("Wallet access requires HTTPS")
        local, networks = "", ()
        if options.get("local_http_enabled", False):
            local = validate_origin(options.get("local_http_origin"), "http")
            if "local_http_networks" in options:
                # Legacy settings remain an upper bound until the owner saves options.
                networks = tuple(
                    ip_network(item, strict=True)
                    for item in _items(options["local_http_networks"])
                )
                if not networks or any(
                    not any(
                        n.version == allowed.version and n.subnet_of(allowed)
                        for allowed in LOCAL_RANGES
                    )
                    for n in networks
                ):
                    raise ValueError("Invalid legacy local networks")
                if detected_networks is not None:
                    networks = tuple(
                        set(
                            n if n.subnet_of(old) else old
                            for n in detected_networks
                            for old in networks
                            if n.version == old.version and n.overlaps(old)
                        )
                    )
            else:
                networks = detected_networks or ()
        proxies = tuple(
            ip_address(item) for item in _items(options.get("https_proxy_ips", ""))
        )
        if any(ip.is_unspecified or ip.is_multicast for ip in proxies) or (
            proxies and not https
        ):
            raise ValueError("Invalid HTTPS proxy")
        if not https and not local:
            raise ValueError("At least one origin required")
        return cls(https, local, networks, proxies)

    def check(self, request: web.Request, ha_trusted=()) -> str:
        """Return validated client IP; never use forwarded data for local HTTP."""
        if remote.is_cloud_request.get():
            raise AuthError(403, "cloud_transport_unsupported")
        if request.transport is None:
            raise AuthError(403, "transport_denied")
        tls = request.transport.get_extra_info("ssl_object") is not None
        raw_peer = request.transport.get_extra_info("peername")
        try:
            peer = ip_address(raw_peer[0]) if raw_peer else None
        except ValueError, TypeError:
            peer = None
        forwarded = any(
            name in request.headers
            for name in (
                "Forwarded",
                "X-Forwarded-For",
                "X-Forwarded-Proto",
                "X-Forwarded-Host",
            )
        )
        host_values = request.headers.getall("Host", [])
        if len(host_values) != 1:
            raise AuthError(403, "origin_denied")
        host, source = host_values[0].lower(), str(peer) if peer else "unknown"
        ha_proxy = peer is not None and any(peer in network for network in ha_trusted)
        if forwarded:
            # One explicitly trusted hop. HA must also have validated and cloned
            # the request; reject ambiguous chains and unsupported Forwarded syntax.
            if (
                peer not in self.proxy_ips
                or not ha_proxy
                or "Forwarded" in request.headers
            ):
                raise AuthError(403, "proxy_denied")
            clients = request.headers.getall("X-Forwarded-For", [])
            protos = request.headers.getall("X-Forwarded-Proto", [])
            hosts = request.headers.getall("X-Forwarded-Host", [])
            if len(clients) != 1 or protos != ["https"] or len(hosts) > 1:
                raise AuthError(403, "proxy_denied")
            try:
                client = ip_address(clients[0].strip())
            except ValueError:
                raise AuthError(403, "proxy_denied") from None
            if request.scheme != "https" or request.remote != str(client):
                raise AuthError(403, "proxy_denied")
            host = hosts[0].lower() if hosts else host
            if request.host.lower() != host:
                raise AuthError(403, "proxy_denied")
            origin, source = self.https_origin, str(client)
        elif tls:
            origin = self.https_origin
        else:
            # Known proxies must never fall back to LAN access if they omit headers.
            if (
                peer is None
                or peer in self.proxy_ips
                or ha_proxy
                or not any(peer in network for network in self.local_networks)
            ):
                raise AuthError(403, "local_http_denied")
            origin = self.local_origin
        origins = request.headers.getall("Origin", [])
        if (
            not origin
            or host != urlsplit(origin).netloc
            or (origins and origins != [origin])
        ):
            raise AuthError(403, "origin_denied")
        if request.query_string:
            raise AuthError(400, "query_not_allowed")
        return source


class LocalNetworkUnavailable(ValueError):
    """HA exposes no usable enabled private adapter network."""


def adapter_networks(adapters: list) -> tuple:
    """Use HA-enabled interfaces and their real prefixes; never guess a /24."""
    networks = set()
    for adapter in adapters:
        if adapter.get("enabled") is not True:
            continue
        for info in (*adapter.get("ipv4", []), *adapter.get("ipv6", [])):
            try:
                address, prefix = info["address"], info["network_prefix"]
                if type(prefix) is not int or type(address) is not str:
                    continue
                interface = ip_interface(f"{address}/{prefix}")
                network = interface.network
                if interface.ip.is_loopback or interface.ip.is_link_local:
                    continue
                if any(
                    network.version == allowed.version and network.subnet_of(allowed)
                    for allowed in LOCAL_RANGES
                ):
                    networks.add(network)
            except ValueError, KeyError, TypeError:
                continue
    return tuple(
        sorted(networks, key=lambda n: (n.version, int(n.network_address), n.prefixlen))
    )


async def async_transport_policy(
    hass, options, *, require_local: bool = False
) -> TransportPolicy:
    """Refresh from HA's adapter state; detection failure disables local HTTP only."""
    networks = ()
    if (
        options.get("guest_enabled") is True
        and options.get("local_http_enabled") is True
    ):
        try:
            networks = adapter_networks(await async_get_adapters(hass))
        except HomeAssistantError, OSError, ValueError, TypeError, KeyError:
            networks = ()
    policy = TransportPolicy.from_options(options, detected_networks=networks)
    if policy.local_origin and not policy.local_networks and require_local:
        raise LocalNetworkUnavailable("No private HA network detected")
    return policy
