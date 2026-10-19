# API boundaries and authentication

The five owner grant commands are implemented in Phase 2 using a `payload` envelope, documented with runnable message examples in [Phase 2](phase-2.md). Phase 3 implements invitation issuance and the guest endpoints below, gated by explicit owner HTTPS options; they default off. See the [Phase 3 workflow and protocol](phase-3.md). There is no execute command on the owner API.

## Administrative API

Use HA's authenticated `/api/websocket` with integration command types. Require the active HA **owner**, not merely any authenticated user or admin, on every command. Re-resolve current user status rather than trusting a long-lived connection's stale role. Ordinary administrators are deliberately excluded from v0.1; delegation can be a future explicit policy. [HA WebSocket API](https://developers.home-assistant.io/docs/api/websocket/).

| Command type | Input | Result |
| --- | --- | --- |
| `solbuddy_access/grants/create` | Name, optional identifier, timestamps, entity/action policies | Persisted grant with server ID and derived status |
| `solbuddy_access/grants/list` | Bounded cursor/page size | Owner-visible redacted grant summaries |
| `solbuddy_access/grants/get` | Grant ID | Grant and policy details |
| `solbuddy_access/grants/revoke` | Grant ID | Durable revocation result; repeated revocation is idempotent |
| `solbuddy_access/grants/check` | Grant ID and proposed typed action | Advisory authorization decision; never executes |

Server-owned fields are forbidden in input. No administrative command accepts an owner ID or status override. There is no guest-facing create/list/revoke operation, and no owner shortcut that bypasses the common policy engine to simulate guest control.

## Local guest authentication

Use random capability credentials rather than passwords or HA tokens. Phase 3 implements and tests this lifecycle. TLS is the default; local HTTP requires a separate owner opt-in and automatically detected private HA adapter networks. The current transport supports direct HTTPS, explicitly trusted single-hop proxy HTTPS, and opt-in local HTTP. See [transport configuration and trust boundaries](transports.md). No port forwarding or public deployment is part of v0.1 setup.

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

No grant ID, service name, template, target array, device ID, or raw HA data is accepted. Validate strict object shape and size before expensive work. Implemented limits: 8 KiB bodies, bounded header lengths, one in-flight operation/session, 30 requests/minute/session with burst 5, and a bounded global limiter for authentication attempts. Source-IP limits supplement global/session limits but never establish identity; forwarded addresses are accepted only through the validated trusted-proxy path. Keep limiter maps bounded and use monotonic time.

Consume sequences even on denied actions; do not replay on timeout. Return a bounded receipt with outcome `dispatched`, `denied`, or `unknown`; HA accepting a service call is not proof the physical device changed. Missing/invalid credentials return generic 401; invalid input 400, denied active-session operations 403, sequence conflicts 409, limits 429, and unavailable security dependencies 503. Error bodies must not disclose other grants/entities. An expired/revoked session receives 401 without explaining grant existence.

## Enablement gate

Before guest routes exist, test authentication, expiry, rotation, cross-grant isolation, replay races, TLS/proxy assumptions, header redaction, size/rate limits, and absence of any unauthenticated path using actual HA HTTP fixtures. Test that SOLBUDDY credentials fail on HA's ordinary API and HA credentials are not silently accepted as guest credentials. Document and review the complete credential lifecycle and client storage before enabling control. The Phase 3 authentication, TLS, and owner-options tests passed before the source registration gate was opened. Runtime guest access still defaults off; fresh installations register no guest routes until the owner opts in. See [validation and limitations](phase-3.md).

## Optional wallet grants (0.1.0.dev6)

See [wallet setup](wallet-access.md). Wallet challenge/verification routes require enabled guest **and** wallet access and HTTPS. `/wallet/owner` instead always requires a native active HA owner and remains available with guest access disabled, over the existing HA connection. `/wallet/info` reports safe enablement/signing-URL metadata through the guest transport policy. Wallet public keys are managed over HTTP, not WebSocket, to avoid HA's WebSocket debug response logging. WebSocket creation rejects `wallet_address`; WebSocket reads redact that field.

| POST path under `/api/solbuddy_access/v1` | Authentication | JSON body |
| --- | --- | --- |
| `/wallet/owner` | Native HA owner bearer | `{"operation":"create","payload":{...}}`, `{"operation":"list","payload":{}}`, or `{"operation":"revoke","payload":{"grant_id":"..."}}` |
| `/wallet/challenge` | `SolbuddyInvite <invitation>` | `{}` |
| `/wallet/verify` | Same invitation | `{"signature":"<canonical base64 of 64-byte Ed25519 signature>"}` |
| `/wallet/renew-challenge` | `SolbuddySession <session>` and next sequence | `{}` |
| `/wallet/renew` | Same session and next sequence | `{"signature":"<canonical base64>"}` |

Create payload is the normal immutable light grant payload plus the owner-approved `wallet_address`. The fixed wallet policy cannot be overridden. Each challenge returns `message`, `wallet_address`, and `expires_at`; sign the exact UTF-8 message. The server stores and verifies those bytes, not client-supplied challenge fields. Successful verification returns the normal session response with sequence reset to 1. Renewal challenge and verification each consume a sequence. Prices, balances and authorization decisions are never accepted from clients.

`/session` and `/session/renew` reject wallet grants with `wallet_proof_required`. Successful wallet sessions use the existing `/permissions`, `/check`, and `/execute` protocol, including explicitly enabled local HTTP command transport. Wallet proof itself remains HTTPS-only. Errors include `invalid_wallet_proof`, `eligibility_stale`, `eligibility_unavailable`, and `insufficient_sbud`. Failure does not extend a session; uncertain device commands must not be retried blindly.

GET `/wallet/owner-ui` redirects to the native `/solbuddy-access` panel. GET `/wallet/ui` serves the public guest shell on either address, including a disabled-state explanation. Public assets contain no secrets; guest APIs still enforce enablement and transport boundaries. Owner data and mutations always require a current native HA owner session.


## Native HA panel and session transfer (0.1.0.dev7)

`/solbuddy-access` is a custom HA sidebar panel. It uses `hass.callApi` with the current HA auth session; no pasted long-lived token, browser token storage, or secret-bearing WebSocket response is introduced. POST `/wallet/owner` also accepts `status` with empty payload and returns flags, supported-light choices and the HTTPS signing origin. Only an authenticated owner status request can remember a new HTTPS origin. The old owner-ui URL redirects to the panel; public assets contain no owner data. List/revoke/status remain available when guest access is disabled.

POST `/session/transfer` uses the current session authorization and next sequence, with `{}` body. It returns a `transfer_code` and `expires_in: 120`. POST `/session/claim` uses `Authorization: SolbuddyTransfer <code>` and `{}` body, and returns a replacement session with sequence 1. Claim consumes the code exactly once, requires the original session and grant still be live, invalidates the old session, and preserves the old wall-clock and monotonic expiry plus rate limiter. No new eligibility lifetime is granted. Both endpoints obey local/remote guest transport checks. Restart, disabling, revocation, invitation replacement and session replacement make old codes unusable.


## Freshness error details (0.1.0.dev8)

HTTP 503 `eligibility_stale` retains its existing code and adds `observations.price` and `observations.balance`. Each contains only `status` (`fresh`, `stale`, `future`), integer `age_seconds` (negative for future observations), and `max_age_seconds` (300 price / 60 balance). These diagnostics are returned only after successful wallet proof and eligibility evaluation, including final rechecks before issuance/renewal. Both observations can fail simultaneously. `eligibility_expired` means the 30-second evidence deadline expired while source observations were still fresh; it has no observation details. Invalid identity or malformed provider data remains a generic unavailable error. Existing no-store headers apply.


## Verified-wallet preview (0.1.0.dev9)

After a valid Ed25519 wallet proof, errors `eligibility_stale`, `eligibility_expired`, `eligibility_unavailable` and `insufficient_sbud` retain their existing HTTP status and safe diagnostics, and may add `preview`: `{wallet_verified: true, controls_enabled: false, grant_expires_at: <ISO timestamp>, policies: [...]}`. Policies include only the same entity/action/parameter-limit fields exposed by guest permissions, never registry identifiers or wallet/credential data. The grant expiry is distinct from a session expiry; no session is created by this response.

The server rechecks the original credential, grant, storage/audit health and proof deadline under the grant gate after any provider/audit awaits before disclosing this snapshot. Wrong/replayed proofs and revoked/expired state get no preview. Clients must not treat the preview as authorization: existing session credentials remain mandatory for all commands. Retrying requires a new challenge/signature and the existing valid invitation or session.
