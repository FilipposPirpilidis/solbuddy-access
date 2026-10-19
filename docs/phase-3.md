# Phase 3: secure guest sessions

**Transport update:** Version 0.1.0.dev4 adds optional local HTTP and trusted-proxy HTTPS. Follow [the current transport setup](transports.md); it supersedes the original direct-TLS-only instructions below. The credential protocol is unchanged.

Phase 3 adds invitation exchange, rotating sessions, and a dedicated HTTPS guest API. Guest access **defaults off**. The implementation security suite passed before the source registration gate was opened. No live Home Assistant installation has been enabled or deployed by this change.

## Enablement and owner workflow

1. Use a disposable HA 2026.10.2 installation with direct HTTPS and a trusted certificate. TLS must reach HA itself. TLS-terminating reverse proxies, forwarded headers, and IPv6 origin literals are unsupported in this phase. No public exposure is required.
2. Install the integration and create the single-light grant using the [owner WebSocket commands](phase-2.md). The reviewed adapter still accepts only individual core Hue v2 lights. Verify downstream automations before choosing a light.
3. As the active HA owner, open the integration's options **over that direct HTTPS connection**, enable guest access, and enter its exact origin, including a non-default port. Ordinary administrators cannot enable it. Options reload invalidates existing credentials.
4. Issue an invitation using `POST /api/solbuddy_access/v1/invitations`, native `Authorization: Bearer <owner HA access token>`, and JSON `{"grant_id":"<owner-created grant ID>"}`. Transfer only the returned invitation through a trusted private channel. Never give a guest the HA token.
5. The guest runs the example below and pastes the invitation into its hidden prompt. Use `permissions`, then `on` or `off` with the approved entity ID. `renew` rotates the session before its 15-minute expiry; `quit` discards client memory.
6. Revoke through the owner WebSocket API. Revocation immediately invalidates credentials, including while its durable save is pending. Disabling guest access or unloading/restarting also invalidates every credential.

Invitations use HTTP rather than WebSocket because the pinned HA WebSocket DEBUG logger records outbound response bodies. The integration never issues secrets through that logger.

An owner can issue an invitation without putting credentials in shell history or command arguments using this Python snippet in a private terminal (replace only the origin and grant ID). It verifies certificates, refuses redirects, and intentionally displays the one-time invitation for private transfer:

```python
import getpass, http.client, json, ssl
connection = http.client.HTTPSConnection(
    "ha.example", 8123, context=ssl.create_default_context(), timeout=20
)
owner_token = getpass.getpass("Owner HA token: ")
connection.request(
    "POST", "/api/solbuddy_access/v1/invitations",
    json.dumps({"grant_id": "REPLACE_WITH_GRANT_ID"}),
    {"Authorization": "Bearer " + owner_token, "Content-Type": "application/json"},
)
del owner_token
response = connection.getresponse()
if response.status == 200:
    print(json.loads(response.read(8192))["invitation"])
else:
    print("Invitation failed:", response.status)
connection.close()
```

For a private CA, pass its certificate as `cafile` to `ssl.create_default_context`; never disable verification. Do not run the invitation snippet in a recorded terminal or notebook.

```sh
python examples/guest_client.py https://ha.example:8123
# Optional private CA trust:
python examples/guest_client.py https://ha.example:8123 --ca-file /path/to/ca.pem
```

The [minimal guest client](../examples/guest_client.py) uses only Python's standard library, stores credentials only in memory, verifies TLS, never follows redirects, and never automatically retries. It exits on any HTTP error or uncertain response; request a replacement invitation to recover. It is a protocol demonstration, not a guest UI or credential vault. Python cannot guarantee secure memory erasure.

## Protocol

All paths start with `/api/solbuddy_access/v1`. No query parameters, credential cookies, or cross-origin requests are accepted. Host must match the configured origin. Requests with an Origin must match it exactly. Forwarded headers are rejected; actual socket TLS and peer addresses are used.

| Method/path | Authorization | Body / result |
| --- | --- | --- |
| POST `/invitations` | Native HA `Bearer` owner token | `grant_id`; returns `invitation`, `expires_at` |
| POST `/session` | `SolbuddyInvite sbai_…` | Empty object; returns `session_token`, `expires_at`, `next_sequence: 1` |
| POST `/session/renew` | `SolbuddySession sbas_…` | Empty object; returns replacement token and sequence 1 |
| GET `/permissions` | `SolbuddySession sbas_…` | No body; own grant expiry and permitted entity/actions/limits only |
| POST `/check` | `SolbuddySession sbas_…` | Action payload; returns `allowed` |
| POST `/execute` | `SolbuddySession sbas_…` | Action payload; returns `outcome` |

Each session operation requires `X-Solbuddy-Sequence` with the exact next decimal integer, starting at 1, up to 2147483647. One request may be in flight per session. Admission consumes the sequence even when later body validation or policy checks deny the request. A pre-admission rate limit or sequence conflict does not consume it. Do not infer whether admission happened from an HTTP timeout: stop and obtain a new invitation. Never retry an uncertain device action automatically.

The action payload contains exactly `entity_id`, `action`, and `parameters`, as documented in [API boundaries](api.md). Session requests never accept a grant ID or owner identity. A dispatch receipt is not proof of a physical device change; `unknown` can mean a call happened but its completion is uncertain.

Limits: 8 KiB JSON bodies, 5-second body read deadline, no compressed bodies, no duplicate keys or nonfinite JSON constants, session burst 5 with 30/minute refill, socket-source burst 20 with 20/minute refill, global burst 60 with 120/minute refill. Source buckets are bounded at 256 and expire after five idle minutes. Rotation preserves the session rate budget. HA's own HTTP parser limits also apply.

Responses use no-store headers. Statuses: invalid credentials 401; invalid payload 400; oversized body 413; forbidden policy/origin/TLS 403; sequence conflict 409; rate limit 429; unavailable security state 503. Disabled routes return 404 (already registered owner invitation routes may still encounter HA authentication first).

## Credential lifecycle and security review

Both credential types contain 256 bits from `secrets.token_urlsafe(32)`, with separate prefixes. Only SHA-256 digests are kept in volatile memory and comparisons use `hmac.compare_digest`. There is at most one invitation and one session per grant, bounded by the 100-grant limit. Invitations expire after five minutes and are atomically consumed before audit IO. Sessions expire after 15 minutes. Both are capped by grant expiry and checked using UTC and monotonic deadlines.

Issuing a replacement invitation invalidates the old session. Renewal atomically replaces the token, resets its sequence space, and rechecks grant/credential validity after awaited audit IO. No refresh token survives expiry. Restart, reload, disablement, revocation, or replacement requires a fresh invitation. Stored grants alone cannot restore credentials from a backup.

The shared execution gate rechecks the live session immediately before dispatch, after durable audit admission. Expiry, revocation, storage/audit faults, and clock integrity faults fail closed. Already dispatched physical operations cannot be canceled. Bearer theft still permits fresh authorized requests until invalidation; sequence checks prevent replay, not theft or impersonation with a stolen token.

Tests exercise real HA HTTP middleware over verified local TLS, actual native storage, synthetic Hue registry fixtures and HA service calls. They cover credential separation, invitation reuse/races, session rotation, replay/in-flight exclusion, expiry at final dispatch, revocation including save failure, bounded rate maps and bodies, exact origin checks, plaintext/proxy rejection, owner-only options, disablement, and DEBUG-log credential exclusion. These are local implementation tests, not an independent security audit or real-bridge certification. Phase 4 climate and Phase 5 release readiness remain outstanding.

## Validation evidence — 2026-10-19

- Full suite: **191 passed**, **92%** integration statement coverage, Python 3.14.2 / HA 2026.10.2.
- The initial 64-test authentication, HTTPS, and owner-options suite passed with the production gate still closed; full regressions and additional race/WebSocket tests passed after opening the source gate.
- `uv sync --locked --group dev`, Ruff check and format check for integration/tests/example, and the official HA 2026.10.2 **manifest-only** validator passed.
- Example CLI help was smoke-tested; its underlying exchange/control protocol was tested through real local HTTPS. No live HA installation, real bridge, public endpoint, or deployment was used. Full hassfest and hardware release checks remain outstanding.
