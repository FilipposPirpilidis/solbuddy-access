# Automatic HA connections (0.1.0.dev7)

Current setup: [wallet and native owner panel guide](wallet-access.md). SOLBUDDY now uses HA network interfaces, URL settings and trusted proxy middleware. Duplicate origin, proxy and subnet fields are removed. Guest access enables direct local HTTP and recognized HTTPS; wallet signing remains HTTPS-only. Cloudflare-style forwarding chains are covered by HA middleware tests. Owner management remains accessible with guest access disabled.

The text below records the superseded dev5 transport implementation; its configuration fields and restrictions are not current setup instructions.

# Local HTTP and remote HTTPS (0.1.0.dev5)

This update supports guest invitations, sessions, and commands over an explicitly enabled local HTTP connection and remote HTTPS simultaneously. Guest access and local HTTP both default off. Existing HTTPS-only settings remain HTTPS-only after upgrade. Wallet and coin eligibility are not implemented.

## Update and configure

Replace the installed `custom_components/solbuddy_access` folder with this version and restart Home Assistant. Keep your `configuration.yaml` unchanged if your HTTPS proxy already works with HA. As the HA owner, open Settings → Devices & services → SOLBUDDY Access → Configure (options).

For example, if HA itself is at `http://192.168.68.10:8123` and the HTTPS proxy is `192.168.68.112`, use:

| Option | Example |
| --- | --- |
| Enable guest access | On |
| HTTPS origin | `https://ha.example.com` — your real remote address, no path |
| Allow unencrypted local HTTP | On |
| Local HTTP origin | `http://192.168.68.10:8123` — your actual HA address |
| HTTPS proxy IP addresses | `192.168.68.112` |

The HA address above is illustrative; use your actual HA address, such as `http://homeassistant.local:8123`. You no longer enter a subnet. SOLBUDDY uses the addresses and real subnet prefixes of **enabled Home Assistant network adapters**. Only RFC1918 IPv4 and IPv6 ULA networks are eligible; public, link-local, loopback, and disabled interfaces are excluded. No guessed `/24`, hostname-based trust, or allow-all fallback is used. Origin hostnames and IPv4 literals are supported; IPv6 origin literals remain unsupported.

If HA reports no eligible network, saving enabled local HTTP settings shows an error. At runtime, missing network information blocks local HTTP while configured HTTPS continues working. Check HA's Settings → System → Network selection. With a container, HA must see the LAN interface (a bridge-only container may expose only its container subnet). SOLBUDDY consults HA's current adapter state on each request; restart HA after OS address/prefix changes that HA has not refreshed.

On upgrade, any previously saved manual subnet list remains an additional restriction intersected with detected networks. Saving the new options removes that legacy restriction and adopts automatic detection. Existing HTTPS-only installations remain HTTPS-only.

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

Tests cover automatic private-adapter detection and legacy subnet restrictions, outside/public sources, proxy peers attempting local fallback, untrusted and spoofed forwarding, downgrade and chain rejection, exact origin/Host checks, HA cloud transport exclusion, owner local configuration, and real HA HTTP middleware invitation → session → light execution for both local HTTP and forwarded HTTPS. Existing verified direct-TLS and all grant/session tests remain in the suite. Device fixtures are synthetic; no production HA instance or physical light was changed.

Validation on Python 3.14.2 / HA 2026.10.2: **229 tests passed**, **92%** integration statement coverage; Ruff check/format and the official HA manifest-only validator passed. Full hassfest and testing on real hardware remain release checks.


Automatic detection follow-up: the manual subnet field has been removed from options and translations. Tests cover actual prefixes, multiple enabled adapters, public/link-local/loopback exclusion, disabled interfaces, detection failure, changed HA adapter state, options errors, and preserving legacy restrictions until owner save.

Validation for 0.1.0.dev5: 235 full-suite tests plus the additional options error/removed-field test passed (236 total). Ruff, locked dependency sync, manifest-only validation, and translation parity passed.
