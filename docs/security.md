# Security model and verification plan

Phase 3 implements the guest controls below; this is not a security certification. The local authentication/TLS suite passed before the source gate opened. Guest control still defaults off. See [Phase 3 validation and limitations](phase-3.md).

## Trust assumptions and limits

Local HTTP is now an explicit owner opt-in. It exposes credentials and commands to network interception; private-source checks do not provide encryption or prove physical location. Known proxy peers are excluded from the local allowance. See [transport boundaries and deployment limitations](transports.md).

Trust the HA host, its owner, installed integrations, OS, and direct HA TLS or the explicitly trusted single-hop HTTPS proxy. Treat guests, client payloads, credentials received over the network, and stale stored data as untrusted. Protect against malicious guests and accidental overbroad delegation. A compromised HA owner, malicious integration, or filesystem administrator can bypass an in-process integration; SOLBUDDY cannot sandbox HA itself.

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
| Denial of service | Bounded payloads, sessions, queues, global authentication and per-session rate limits; HA/host connection limits; single-hop TLS proxies require explicit HA and SOLBUDDY trust |
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

## Optional wallet authentication

Wallet access defaults off independently of the guest transport. Owner approval, a grant-scoped invitation, a fresh one-time Ed25519 proof, finalized exact-mint holdings, and fresh server-side USD valuation are all required. HTTPS is mandatory for wallet proof. Administration uses the native HA owner login and same-origin requests on the existing HA connection. Grant schema 3 pins the wallet and policy; ordinary session exchange/renewal cannot authenticate a wallet grant. Revoke-and-replace is required to change wallets.

Provider responses are bounded, redirects denied, and the entire eligibility operation timed out. RPC genesis, Token-2022 ownership, mint properties, account ownership, integer balances and source timestamps are validated. Price observations older than 300 seconds and balance snapshots older than 60 seconds are rejected, including a freshly retrieved stale price. No secondary-price fallback exists. Decimal arithmetic preserves the exact US$2 threshold. The configured RPC and Jupiter remain trusted external data sources; this is not a manipulation-resistant independent price oracle for a thin market.

External IO does not hold the grant revocation gate. Before session issuance, recheck credential identity, grant validity, storage/audit health, challenge deadline, and evidence age, including after awaited audit admission. Proof is reserved before external IO; concurrent replay cannot create a second session. Failed renewal does not extend the existing credential. Balance transfers are only detected at renewal; existing sessions may remain usable for up to 15 minutes. Owner revocation remains immediate at subsequent authorization.

Bundled pages avoid browser storage, URL credentials, CDN code and iframe embedding. Owner HTTP APIs re-resolve current ownership. Provider credentials stay server-side with optional HA `!secret` configuration. Third-party RPC observes queried public wallets. Signature and balance test fixtures are synthetic. Manual testing of actual wallets and devices remains a release requirement; mobile QR/deep-link connection is not implemented. See [setup and limits](wallet-access.md).


## HA-managed connections and owner panel (0.1.0.dev7)

Guest origins are derived from HA URL settings, legacy HTTPS configuration and an HTTPS origin observed by an authenticated active-owner status request. Unauthenticated input cannot establish a trusted origin. Local origins are HA internal HTTP URL, homeassistant.local with the HA port, and detected enabled private adapter IPv4 addresses. Direct LAN membership and exact local origin are both required; known HA proxy peers are excluded. Forwarded traffic requires a trusted socket peer and the client/scheme selected by real HA middleware, including its trusted-chain algorithm. Plaintext forwarding, mismatched origin, cross-site requests, and untrusted spoofed forwarding are rejected. CF headers alone convey no authority. Native owner management does not depend on guest enablement, and every administrative API call rechecks active ownership.

Session transfer uses 256-bit random one-time codes, stored only as digests with the original credential identity, capped at one per grant and a two-minute deadline. Claim reserves before awaited IO and rechecks the session under the grant gate before and after audit admission. Replay, concurrent claim, expired source sessions, stale replacement sessions, and revocation fail closed. Transfer never extends the eligibility window or resets the rate limiter. UI transfer is explicit copying between pages, with no credentials in URLs or browser storage. Local HTTP remains unencrypted as explicitly requested.

The forwarded-header integration follows HA 2026.10.2's `http/forwarded.py` behavior. Cloudflare documents forwarding `X-Forwarded-For` and `X-Forwarded-Proto`; SOLBUDDY relies on HA's trusted-peer validation rather than treating Cloudflare-specific headers as proof. [Cloudflare HTTP header reference](https://developers.cloudflare.com/fundamentals/reference/http-headers/)
