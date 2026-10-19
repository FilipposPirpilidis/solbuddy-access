# Phase 2 backend and owner API

Phase 2 implements owner grant management and the internal single-light execution boundary. Guest authentication still always denies; no guest HTTP view, WebSocket execute command, HA service, invitation, or session has been added. Internal execution is called directly by tests with a synthetic verified grant binding. Phase 3 must implement actual guest authentication before any guest can use it.

## Supported enrollment

Initially accept only the core `homeassistant.components.hue.v2.light.HueLight` implementation with a physical device, an active Hue config entry, enabled matching registry/device records, and an available state. Hue groups, rooms, zones, v1 lights, templates, custom implementations, climate entities, locks, and unknown platforms fail closed. The adapter was reviewed against the installed HA 2026.10.2 source; there has been no physical bridge/device test yet.

Each grant binds the exact entity ID, registry entry ID, config entry ID, device ID, and unique ID. Recheck them and capabilities before dispatch. Entity renames, replacement, removal, disabled entries, and unavailable state require denial; owners must revoke and replace grants when enrollment changes. Existing automations and physical wiring remain the owner's responsibility: changing a permitted light can trigger an owner-authored automation outside this integration.

## Owner WebSocket commands

Connect to HA's standard `/api/websocket` and authenticate with the owner's existing HA session. Keep that credential exclusively with the owner. Every command re-resolves the current user and rejects nonowners, inactive/deleted users, and system identities. There is no custom login endpoint.

The command envelope has `id`, `type`, and `payload`. Additional top-level fields are rejected by HA; operation-specific payload fields are strictly checked. Payloads are limited to 8 KiB. Each owner request uses a distinct HA WebSocket message ID.

Create a grant using current/future timezone-aware timestamps. This illustration spans exactly 72 hours; replace the dates before sending:

```json
{
  "id": 1,
  "type": "solbuddy_access/grants/create",
  "payload": {
    "guest_display_name": "Guest A",
    "starts_at": "2026-10-19T15:00:00Z",
    "expires_at": "2026-10-22T15:00:00Z",
    "policies": [
      {"entity_id": "light.guest_room", "actions": ["turn_on", "turn_off"]}
    ]
  }
}
```

The server generates the grant ID and owner attribution, resolves bindings, and saves before responding. The guest identifier is optional metadata, never authentication. `created_by`, `status`, registry IDs, device IDs, and arbitrary service data cannot be supplied. One reviewed light per grant is supported in this milestone. Policies are immutable; revoke and replace to change them.

| Command suffix | Payload | Result |
| --- | --- | --- |
| `create` | Creation object above | Persisted grant with server fields and current status |
| `list` | Optional integer `offset` (0–100), `limit` (1–50; default 20) | Redacted summaries and `next_offset` |
| `get` | `grant_id` | Full owner-only grant and current status |
| `check` | `grant_id`, `entity_id`, `action`, `parameters` | Advisory `allowed` and fixed reason code; no execution |
| `revoke` | `grant_id` | Persisted revoked grant and `audit_degraded` flag |

Use the returned grant ID in these requests:

```json
{"id":2,"type":"solbuddy_access/grants/list","payload":{"limit":20}}
{"id":3,"type":"solbuddy_access/grants/get","payload":{"grant_id":"RETURNED_GRANT_ID"}}
{"id":4,"type":"solbuddy_access/grants/check","payload":{"grant_id":"RETURNED_GRANT_ID","entity_id":"light.guest_room","action":"turn_on","parameters":{}}}
{"id":5,"type":"solbuddy_access/grants/revoke","payload":{"grant_id":"RETURNED_GRANT_ID"}}
```

An explicit brightness policy may add `set_brightness` to actions and specify `brightness_min`, `brightness_max`, and `turn_on_brightness` together. Bounds are inclusive integers within 1–255; booleans, strings, relative brightness, and zero are rejected. Plain turn-on uses the owner's explicit default brightness when bounded. Brightness-setting can turn on the light and is explicitly granted as such.

Errors use generic `not_allowed`, `invalid_format`, or `unavailable` codes without reflecting raw request bodies. Registered handlers resolve the live runtime, so reload does not retain a stale manager. An unloaded integration denies commands. Pagination is a bounded view, not a transactionally frozen list.

## Authorization, revocation, and audit

The manager owns per-grant gates and limits non-revocation work to eight waiting/admitted requests per grant. Waiting for a gate times out after 15 seconds. Revocation sets an in-memory denial marker before waiting, then persists while holding the gate. Owner identity is checked again after acquiring it. Successful acknowledgement means no new dispatch can occur. A command already handed to HA may still finish; it cannot be recalled.

The internal executor constructs only `light.turn_on` or `light.turn_off`, with one exact entity and optional validated brightness. It never accepts a caller-selected service, group, area, script, or device target. HA context does not impersonate the owner. Service invocation is bounded to ten seconds; errors/timeouts have an unknown physical outcome and are never automatically retried.

Before dispatch, persist an audit admission and then recheck authorization, expiry, device binding, availability, and health. This catches a grant expiring or a device changing during disk IO. A wall-clock jump relative to monotonic time latches execution closed until a new runtime; revocation remains available. The host's time is trusted at startup.

Audit data is a separate private native Store so a failed audit does not prevent saving a revocation. It contains opaque IDs, timestamps, enumerated event/action values, and operation correlation IDs—no guest names, identifiers, credentials, raw payloads, or arbitrary exception text. Records are pruned to seven days on the next append and capped at 10,000. Inactive installations can retain old records until another append. An admission without a completion means outcome unknown. `create_requested` records intent, not proof a grant save completed.

Audit admission failure blocks execution. Completion-audit failure returns unknown and blocks later execution. A revocation that persisted still succeeds with `audit_degraded: true` if audit recording fails. A failed grant-store save never reports successful revocation and leaves the repository closed. The UI can still show expired status without a timer: all enforcement uses request-time checks.

## Upgrade and lifecycle

Grant schema v2 adds persistent device/unique-ID bindings. Legacy v1 grants remain readable and revocable but fail execution with `legacy_binding`; replace them to enroll the device. No permissions are widened during loading. The outer Store envelope version stays v1; older builds reject the new grant schema rather than interpreting it permissively.

The first Phase 2 setup initializes a separate audit Store and records `audit_initialized` in the config entry after verification. Once marked, missing/corrupt audit state is not silently recreated. Owner reads and revocation remain available with audit degraded; new grants and execution are blocked. Unload blocks admission, drains creation and admitted execution, then closes storage. Native disk IO can delay completion; timeout/failure must never be presented as a successful revoke.

## Verification and limits

Recorded validation on Python 3.14.2 / HA 2026.10.2: **135 tests passed**, **93% statement coverage**, Ruff lint/format checks passed, dependency lock checked, and documentation links/JSON/translation parity validated.

Tests cover owner WebSocket create/list/get/check/revoke, denial of ordinary admins, role revalidation, missing execution commands, guest-route 404s, exact single-entity service dispatch, forbidden domains/actions/parameters, brightness, future/expired/revoked grants, changing bindings, real disk persistence, audit failures, write failures, both revoke/execute race orderings, clock faults, and unload behavior. Hardware fixtures are synthetic; HA registries, service registry, WebSocket transport, and storage are real test instances.

The selected repository is [FilipposPirpilidis/solbuddy-access](https://github.com/FilipposPirpilidis/solbuddy-access), verified reachable with a `main` branch. Manifest and project metadata point there. Local `origin` points to this repository and local `main` tracks `origin/main`. The owner authorized committing and pushing this Phase 2 implementation with guest endpoints disabled. Official HA 2026.10.2 manifest validation passes; a complete hassfest run and real hardware validation remain release work.
