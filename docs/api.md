# API boundaries and authentication proposal

The five owner grant commands are implemented in Phase 2 using a `payload` envelope, documented with runnable message examples in [Phase 2](phase-2.md). Invitation issuance and every guest endpoint below remain proposals and are not registered. There is no execute command on the owner API.

## Administrative API

Use HA's authenticated `/api/websocket` with integration command types. Require the active HA **owner**, not merely any authenticated user or admin, on every command. Re-resolve current user status rather than trusting a long-lived connection's stale role. Ordinary administrators are deliberately excluded from v0.1; delegation can be a future explicit policy. [HA WebSocket API](https://developers.home-assistant.io/docs/api/websocket/).

| Command type | Input | Result |
| --- | --- | --- |
| `solbuddy_access/grants/create` | Name, optional identifier, timestamps, entity/action policies | Persisted grant with server ID and derived status |
| `solbuddy_access/grants/list` | Bounded cursor/page size | Owner-visible redacted grant summaries |
| `solbuddy_access/grants/get` | Grant ID | Grant and policy details |
| `solbuddy_access/grants/revoke` | Grant ID | Durable revocation result; repeated revocation is idempotent |
| `solbuddy_access/grants/check` | Grant ID and proposed typed action | Advisory authorization decision; never executes |
| `solbuddy_access/invitations/create` | Active grant ID | One-time invitation, shown once; available only after guest-auth gate |

Server-owned fields are forbidden in input. No administrative command accepts an owner ID or status override. There is no guest-facing create/list/revoke operation, and no owner shortcut that bypasses the common policy engine to simulate guest control.

## Proposed local guest authentication

Use random capability credentials rather than passwords or HA tokens. This is a proposed security design requiring implementation review and tests, not a finished authentication mechanism. TLS is mandatory, including on a LAN. Support HA HTTPS or a correctly configured trusted TLS reverse proxy; never trust arbitrary forwarded headers or open CORS. No port forwarding or public deployment is part of v0.1 setup.

1. The authenticated owner creates a random 256-bit invitation for one currently active grant, expiring in five minutes. Only its SHA-256 digest is held in memory. The owner transfers it through a trusted channel; no URLs, QR query parameters, logs, or browser history contain the credential.
2. The guest presents the invitation in an authorization header to `POST /api/solbuddy_access/v1/session`. This is credential authentication, not an anonymous session-creation endpoint. Atomically consume the invitation under the grant gate. Recheck grant activity and storage health. Return a fresh random 256-bit opaque session token once with `Cache-Control: no-store`.
3. All subsequent requests authenticate with that session token in the authorization header. Retain only its digest server-side and compare securely. The session is bound server-side to exactly one grant; requests cannot select another grant or identity.
4. Sessions last at most 15 minutes and never outlive the grant. Before expiry, a valid session may rotate through an authenticated renewal operation that invalidates its predecessor and resets replay state. Recheck the grant on renewal; the overall guest authorization ends with the grant. No unattended recovery after session expiry or restart: the owner must issue a fresh invitation.
5. Start with one active session per grant. Issuing a replacement invitation invalidates the prior session. Guest credential theft is still a bearer-token risk; short duration, TLS, revocation, and secure client memory limit exposure. A stolen token can originate fresh requests; replay detection is not proof of possession.

HA's standard access tokens are never returned to guests. A custom HTTP view may need to opt out of **HA-token** authentication to use this dedicated authenticator. That must never mean an unauthenticated operation: a shared authentication wrapper must reject absent/invalid invitation or session credentials before entering a handler. Do not register any such view until the pinned HA middleware behavior has been verified and the gate below passes. No anonymous discovery, challenge, state, or device-control endpoints are planned.

## Guest operations after the gate

| Endpoint | Credential | Scope |
| --- | --- | --- |
| `POST /api/solbuddy_access/v1/session` | Single-use invitation | Exchange for scoped session |
| `POST /api/solbuddy_access/v1/session/renew` | Current session | Atomically rotate session |
| `GET /api/solbuddy_access/v1/permissions` | Current session | Own grant's permitted controls and expiry only |
| `POST /api/solbuddy_access/v1/check` | Current session | Validate proposed action without executing |
| `POST /api/solbuddy_access/v1/execute` | Current session | Execute one fixed permitted action |

All session requests carry an exact next positive integer sequence in a header. Atomically reserve it before processing; reject duplicates, out-of-order values, and concurrent re-use. One request may be in flight per session. The client serializes requests. Repeated reads must also use fresh sequences. Bound sequence values; rotate before exhaustion. Session rotation and restart invalidate the whole previous sequence space.

Execution payload example:

```json
{
  "entity_id": "light.guest_room",
  "action": "set_brightness",
  "parameters": {"brightness": 100}
}
```

No grant ID, service name, template, target array, device ID, or raw HA data is accepted. Validate strict object shape and size before expensive work. Proposed limits: 8 KiB bodies, bounded header lengths, one in-flight operation/session, 30 requests/minute/session with burst 5, and a bounded global limiter for authentication attempts. Source-IP limits supplement global/session limits but never establish identity; forwarded addresses require HA's trusted proxy configuration. Keep limiter maps bounded and use monotonic time.

Consume sequences even on denied actions; do not replay on timeout. Return a bounded receipt with outcome `dispatched`, `denied`, or `unknown`; HA accepting a service call is not proof the physical device changed. Missing/invalid credentials return generic 401; invalid input 400, denied active-session operations 403, sequence conflicts 409, limits 429, and unavailable security dependencies 503. Error bodies must not disclose other grants/entities. An expired/revoked session receives 401 without explaining grant existence.

## Enablement gate

Before guest routes exist, test authentication, expiry, rotation, cross-grant isolation, replay races, TLS/proxy assumptions, header redaction, size/rate limits, and absence of any unauthenticated path using actual HA HTTP fixtures. Test that SOLBUDDY credentials fail on HA's ordinary API and HA credentials are not silently accepted as guest credentials. Document and review the complete credential lifecycle and client storage before enabling control. Until then, `GuestAuthenticator` returns denial and tests use explicit synthetic principals internally.
