# Incremental implementation roadmap

Status: Phases 1–3 implemented. Phase 3 security tests pass; guest access defaults off and requires explicit owner HTTPS configuration. See [Phase 3 evidence and workflow](phase-3.md). Real-device validation remains a release gate.

| Phase | Deliverables | Exit criteria |
| --- | --- | --- |
| 0 — Architecture review | Architecture, model, API proposal, threat model, repository plan, AGENTS.md | Owner approves scope and proposed defaults |
| 1 — Integration foundation | Manifest, singleton config flow, typed runtime, native storage, models, policy evaluator, pinned Python/HA toolchain, MIT license after attribution confirmation | Config-flow tests, schema and policy tests, storage round trip and fault tests, Ruff and applicable manifest validation pass; no guest routes |
| 2 — First milestone backend | Owner create/list/get/revoke/check WebSocket APIs; exact single-light adapter; durable revocation; audit and concurrency controls | A 72-hour grant allows only selected light actions in the test harness; every forbidden case causes zero service calls; restart and race tests pass |
| 3 — Secure guest access | Reviewed invitation/session lifecycle, TLS-aware HTTP boundary, replay/rate limits, minimal documented client workflow | Real HA transport tests and authentication review pass before guest routes are enabled; owner-to-guest single-light demonstration completes |
| 4 — Complete light/climate v0.1 | Brightness limits, approved climate modes and bounded temperature adapters, device compatibility notes | Full capability and limit matrix passes; unverified device behavior denied; no generalized service proxy |
| 5 — Release readiness | Install/upgrade/remove documentation, supported-version matrix, recovery guide, dependency review and CI | Fresh HA installation and restart/revoke demonstration, all security gates pass, no open critical authorization defect |
| Later — Separate proposals | Management UI, HomeBuddy integration, Solana identity, multi-property support | New design reviews; no changes to local default-deny enforcement |

Phase 2 is a backend milestone, not usable guest access. Phase 3 completes the first **end-to-end** guest milestone. Do not describe v0.1 as complete until Phase 4 scope and Phase 5 release checks pass. If guest authentication cannot be demonstrated safe, ship only the explicitly labeled administrative/test foundation with guest routes absent.

## First milestone acceptance scenario

1. An active HA owner configures the integration and selects a reviewed physical light.
2. They create a grant starting now and ending exactly 72 hours later, allowing turn-on and turn-off on that light only.
3. Before Phase 3, a synthetic authenticated principal exercises the internal service in tests. After Phase 3, the guest exchanges a single-use invitation for a scoped 15-minute session without obtaining a HA account/token.
4. Turn-on and turn-off succeed only for the chosen light. Brightness, any other entity, lock commands, scripts, arbitrary services, and grant modification fail.
5. Pending, expired, and revoked grants fail; the exact expiry boundary fails even when an expiration timer has not fired.
6. Successful revocation blocks all newly dispatched actions, including queued requests. Tests cover both sides of a concurrent revoke/execute race.
7. Restart preserves policy and revocation but invalidates every guest credential. Corrupt storage or failed security checks cause denial.
8. Logs contain useful decisions and outcomes without sensitive credentials.

## Future identity seam

An authentication provider produces an immutable verified principal. A grant-binding resolver maps it to locally approved grants, and the same authorization engine evaluates every operation. Guest-supplied wallet addresses and metadata never establish that binding.

A future Solana proposal must specify challenge uniqueness, domain/audience binding, expiry, signature verification, replay handling, and revocation before any code is added. No chain lookup may override a local revocation or authorize an unsupported domain. $SBUD holdings are not required for v0.1 access. On-chain credentials, wallets, smart contracts, and lock workflows are not part of these implementation phases.

## Review decisions

Approved: owner-only administration; immutable grants; 15-minute rotating guest sessions capped by grant expiry; fresh owner invitation after restart/expired session; HTTPS required; reviewed registry-backed physical devices only; MIT licensing. Phase 2 implements owner administration and the internal execution boundary. Phase 3 implements guest sessions and direct-TLS transport, with owner opt-in required.
