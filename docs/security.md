# Security model and verification plan

This is a proposed design, not a security certification. Guest control remains disabled until the authentication release gate passes.

## Trust assumptions and limits

Trust the HA host, its owner, installed integrations, OS, and configured TLS termination. Treat guests, client payloads, credentials received over the network, and stale stored data as untrusted. Protect against malicious guests and accidental overbroad delegation. A compromised HA owner, malicious integration, or filesystem administrator can bypass an in-process integration; SOLBUDDY cannot sandbox HA itself.

Direct service-call isolation does not prevent an existing HA automation from unlocking a door in response to a permitted light changing. Owners must review downstream automations and the physical function of each enrolled entity. Exclude groups, templates, scripts, and known forwarding integrations; initially accept only reviewed registry-backed device integrations. Domain names alone cannot prove physical safety, and unknown backing implementations must be denied. The milestone is proven with a known single-light fixture and a reviewed real light before release.

## Risks and mitigations

| Risk | Proposed control / remaining limit |
| --- | --- |
| Credential theft | TLS, 256-bit random credentials, digests only, no URLs/logs/localStorage, short sessions, immediate revocation; bearer theft still enables fresh requests until invalidation |
| Replay | Single-use invitations and serialized session sequences consumed atomically; all sessions discarded on restart |
| Cross-grant access / privilege escalation | Server-bound principal, immutable grants, strict per-entity policies, no guest management API |
| Arbitrary HA service execution | Fixed action mapping, one exact target, reject extra fields and all other domains |
| Implicit brightness or HVAC behavior | Explicit bounded on-state where needed, capability checks, deny unverified adapters |
| Revocation races | Shared per-grant execution/revocation gate and durable acknowledgement; already dispatched device work cannot be undone |
| Persistent state corruption | Validated versioned native storage, atomic writes, no permissive fallback, conservative migrations |
| Failed revocation save | Block in memory, invalidate sessions, disable control, report failure; no false success |
| Old backup restores revoked grants | Never persist usable invitations/sessions; restoration requires fresh owner-approved credentials; restored grant records alone do not restore guest access |
| Clock rollback | UTC request checks plus monotonic session deadlines; detect significant wall/monotonic drift and block sessions pending owner recovery; no automatic time tolerance that extends grants |
| Clock wrong at startup | Require sane host time before credential issuance; no entirely offline process can independently prove real-world time after arbitrary clock/backup rollback |
| Denial of service | Bounded payloads, sessions, queues, global authentication and per-session rate limits; reverse-proxy connection limits where deployed |
| Browser misuse | Explicit HTTPS origin, reject unapproved Origin, no credential cookies or permissive CORS, no caching, no browser persistent token storage |
| Entity replacement | Registry/backing identity checks at dispatch, deny changes until owner reapproval |
| Audit leaks | Structured allowlisted fields, no raw exception/request dumps, bounded retention and access restricted to owner |

Revocation is terminal; expiration is authoritative on every request even if timers are late. The system does not promise to revert a light or thermostat when a grant ends. Such automation is separate owner policy and outside v0.1.

## Auditing

Record timestamp, opaque correlation ID, grant ID, actor class, action name, target entity where appropriate, decision reason code, and execution outcome. Guest names, identifiers, token digests, request headers, and raw bodies are excluded. Structured codes prevent attacker-controlled log text. HA service context IDs correlate dispatch without impersonating a homeowner.

Proposed audit retention: seven days or 10,000 records, whichever is smaller, owner-readable only. Persist a redacted admission record before device dispatch; failure denies execution. Record completion afterward; if this write fails, mark audit unhealthy and block further guest execution. A pre-dispatch record without completion means outcome unknown. An audit failure must never stop an owner from revoking access; persist revocation preferentially and report audit degradation. Logging is locally accountable, not tamper-proof against the host owner. Rate-limit and aggregate authentication-failure records to avoid log floods.

## Required tests

| Area | Cases and required evidence |
| --- | --- |
| Time | Pending; start boundary allowed; exact expiry denied; 72-hour interval across DST; clock rollback/drift; expired session under active grant |
| Revocation | Terminal revocation; repeated revoke; current sessions invalidated; denied immediately after successful acknowledgement |
| Authorization | Other entity; other grant; unknown action/domain; every lock action; camera/alarm; owner-only API rejecting ordinary users/admins and missing/system context |
| Validation | Extra fields; arrays/wildcards; invalid entity syntax; booleans/numeric strings; NaN/infinity; oversized bodies; schema versions |
| Light limits | Min/max inclusive; outside limits rejected; brightness zero rejected; unsupported brightness; turn-on cannot restore brightness outside bounds |
| Climate limits | Min/max/step/unit; unsupported mode/features; off-mode bypass; unapproved restored mode/target; unsafe adapter denied |
| Persistence | Save/reload equality; pending/expired/revoked derivation after restart; migration; corrupt/missing store; failed save; stale concurrent snapshots; restore invalidates credentials |
| Concurrency | Deterministic barriers for both revoke/execute orderings; expiry while queued; duplicate sequence races; invitation reuse; rotation race; cancellation and timeout |
| Transport | Real HA WebSocket/HTTP fixtures; current-user revalidation; all guest operations reject missing credentials; tokens cannot cross API boundaries; no routes before gate |
| Privacy/resources | No secrets in logs/errors/diagnostics; bounded rate-limit maps; retention; audit failure blocks execution but permits revoke |
| Lifecycle | Singleton setup; reload without duplicate handlers; unload rejects work; startup failures; capability and registry changes |

Pure policy unit tests must assert deny reasons. Integration tests must additionally assert **no HA service invocation** on denial and an exact single-entity invocation on approval. Use deterministic clocks and async barriers rather than timing sleeps. Do not rely only on final device state to prove absence of unauthorized calls.

## Future lock boundary

Locks remain unconditionally ineligible in v0.1, including through future wallet identity. A later lock feature would require an independently reviewed authorization type, explicit homeowner approval, strong reauthentication, a separate short lifetime, revocation, and comprehensive auditing. Ordinary light/climate grants can never be upgraded implicitly into lock permissions.
