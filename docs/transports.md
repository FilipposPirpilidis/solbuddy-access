# Local HTTP and remote HTTPS (0.1.0.dev4)

This update supports guest invitations, sessions, and commands over an explicitly enabled local HTTP connection and remote HTTPS simultaneously. Guest access and local HTTP both default off. Existing HTTPS-only settings remain HTTPS-only after upgrade. Wallet and coin eligibility are not implemented.

## Update and configure

Replace the installed `custom_components/solbuddy_access` folder with this version and restart Home Assistant. Keep your `configuration.yaml` unchanged if your HTTPS proxy already works with HA. As the HA owner, open Settings → Devices & services → SOLBUDDY Access → Configure (options).

For example, if HA itself is at `http://192.168.68.10:8123`, local clients are on `192.168.68.0/24`, and the HTTPS proxy is `192.168.68.112`, use:

| Option | Example |
| --- | --- |
| Enable guest access | On |
| HTTPS origin | `https://ha.example.com` — your real remote address, no path |
| Allow unencrypted local HTTP | On |
| Local HTTP origin | `http://192.168.68.10:8123` — your actual HA address |
| Allowed local client subnets | `192.168.68.0/24` |
| HTTPS proxy IP addresses | `192.168.68.112` |

The HA address above is illustrative; do not enter it unless it is your HA server's actual address. The local subnet specifies **client source addresses**, not devices granted control. Use exact network CIDRs, separated by commas. Only RFC1918 IPv4, IPv6 ULA, and loopback networks are accepted; no public ranges, wildcard networks, or automatic LAN detection. Origin hostnames and IPv4 literals are supported; IPv6 origin literals remain unsupported.

For local-only use, leave HTTPS origin and HTTPS proxy IP addresses empty. For direct HTTPS, leave the proxy IP addresses empty. Submit options from a connection allowed by the new settings. Disabling all guest access remains possible from any authenticated owner connection. Saving options reloads the integration and invalidates all invitations and sessions.

Local HTTP sends guest credentials and commands without encryption. Owner invitation issuance over HTTP also sends the owner's HA credential without encryption. Use only a LAN you trust. Network allowlists cannot distinguish a local person from traffic relayed through an unlisted local machine or a router that source-NATs public traffic. Do not port-forward the plaintext HA port, and do not route remote users into the local HTTP origin through a tunnel/relay. Keep remote access on the HTTPS proxy.

## Remote HTTPS proxy contract

A single TLS-terminating proxy is supported. The actual socket peer must be an exact IP in SOLBUDDY's **HTTPS proxy IP addresses** and trusted in HA's HTTP configuration. HA must have `use_x_forwarded_for: true`. Your existing `trusted_proxies` entries can remain; add only the actual proxy IPs you use to SOLBUDDY's options. Broad HA proxy trust can prevent local HTTP for clients covered by that range: prefer exact proxy addresses.

The proxy must strip/overwrite client-supplied forwarded headers and send:

- `X-Forwarded-For`: exactly one original client IP.
- `X-Forwarded-Proto`: exactly `https`, only when the public request used HTTPS.
- `X-Forwarded-Host`: your external host and port, or preserve that external `Host` instead.

Redirect or reject public HTTP at the proxy. Its backend connection to HA may use HTTP on the trusted LAN. SOLBUDDY checks the actual proxy peer, HA's validated request scheme/client, and the configured external origin. Unknown proxies, HTTP forwarding, duplicate/ambiguous chains, wrong hosts/origins, and RFC `Forwarded` headers are rejected. Trusted proxy peers cannot use the local HTTP exception even if they omit forwarding headers.

Multiple proxy chains and Nabu Casa Remote UI are not supported by this transport boundary. A Cloudflare → local proxy chain must not be assumed to meet this single-hop contract; it needs separate review. This update does not configure certificates, DNS, routers, firewall rules, or your proxy.

## Credentials and client use

The [Phase 3 invitation/session protocol](phase-3.md) is unchanged. Create an owner-approved single-light grant, issue its invitation, and exchange it for a session. The same grant permissions, expiry, rotation, revocation, sequence checks and rate limits apply to both origins. No guest credential creation UI or wallet feature is added in this update.

The minimal client now supports local HTTP with a deliberate flag and a private IPv4 literal:

```sh
python examples/guest_client.py http://192.168.68.10:8123 --allow-local-http
python examples/guest_client.py https://ha.example.com
```

Paste the invitation into its hidden prompt. HTTPS still verifies certificates, and the client never follows redirects or retries uncertain commands. To issue an invitation locally with the owner Python example in Phase 3, use `http.client.HTTPConnection("192.168.68.10", 8123, timeout=20)` instead of `HTTPSConnection`; the request path, owner authentication, and JSON body remain the same. Prefer HTTPS for owner credentials when available.

## Verification

Tests cover explicit local CIDRs, outside/public sources, proxy peers attempting local fallback, untrusted and spoofed forwarding, downgrade and chain rejection, exact origin/Host checks, HA cloud transport exclusion, owner local configuration, and real HA HTTP middleware invitation → session → light execution for both local HTTP and forwarded HTTPS. Existing verified direct-TLS and all grant/session tests remain in the suite. Device fixtures are synthetic; no production HA instance or physical light was changed.

Validation on Python 3.14.2 / HA 2026.10.2: **229 tests passed**, **92%** integration statement coverage; Ruff check/format and the official HA manifest-only validator passed. Full hassfest and testing on real hardware remain release checks.
