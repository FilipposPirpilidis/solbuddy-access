# Phase 1 implementation status

Historical milestone record. Phase 2 supersedes the endpoint-free runtime and resolves the documentation URL blocker described here. See [current Phase 2 status](phase-2.md).

Architecture and defaults approved on 2026-10-19. Phase 1 code is implemented and validated on macOS with Python 3.14.2 and Home Assistant 2026.10.2. This does not constitute a production guest-access release or broad HA compatibility certification.

## Implemented boundary

The integration can be discovered and configured using the native HA UI. Setup requires a currently active, nonsystem HA owner via HA's authenticated current request. Each flow step resolves the current user again. Missing request context, an ordinary administrator, and forged context user IDs are denied. A single config entry references a randomly named storage record. It contains no secret or guest credential.

Runtime holds the storage repository and a guest authenticator that always denies. No guest HTTP views, administrative WebSocket commands, HA services, device executor, timers, invitation issuers, or session issuers are registered. A real authenticated HA HTTP client receives 404 for every proposed guest route after setup. Unload invalidates repository access; reload validates the existing store.

Validated frozen dataclasses model light grants and action limits. Status is derived from timezone-aware time on every evaluation, with exact-expiry denial and terminal revocation. The evaluator checks grant status, explicit entity/action membership, brightness bounds, storage health, and trusted entity-binding/capability evidence. Its result is an advisory policy preview only. There is no code that turns an allowed result into a device action.

The internal repository exposes add/revoke methods for persistence tests and later application services. These methods are not network APIs and do not authenticate homeowners. A future authenticated grant manager must own those calls and add application-level audit and dispatch concurrency gates.

## Storage guarantees and boundaries

Use native `homeassistant.helpers.storage.Store` with private permissions and atomic writes. A repository lock serializes complete snapshots. Await saves and verify the actual on-disk envelope and unique write revision before accepting the result. HA 2026.10.2 can swallow write failures, so awaiting `async_save` alone is insufficient.

Validate the raw envelope before native loading: exact key, integer major/minor versions, known field set, bounded file size, and valid payload. Native Store can accept unknown minor versions when migration is unimplemented; this repository rejects them before that fallback can rewrite evidence. There are no migrations yet. Any future migration needs an explicit conservative implementation and tests.

Only setup may initialize a new randomly named store. Existing entries never recreate missing data. Invalid/corrupt/version-mismatched files remain preserved, and setup fails closed. Write or cancellation failures make repository access unavailable. An unsuccessful revoke is never reported as successful. A fresh runtime validates persisted state; no guest credentials exist to restore. Local filesystem/host compromise and physical power-loss guarantees are outside the integration's protection boundary.

Storage uses a list of policies with explicit entity IDs; duplicate entity/registry bindings are rejected. Phase 1 caps the whole stored grant collection at 100 rather than implementing archival. All climate and non-light domains remain rejected. Grant creation performs schema validation, but the future application layer must supply authenticated owner identity, trusted time, and enrollment evidence.

## Validation evidence

- **95 pytest tests passed**, including real HA config flow/setup/reload/unload, loopback HTTP route absence, owner checks, model validation, explicit entity/action denials, brightness limits, pending/expired/revoked grants, actual disk round trips, future schema rejection, native swallowed-write errors, cancellation, shutdown, and concurrent persistence writes.
- **95% statement coverage** across the integration in the recorded run. Coverage is supporting evidence, not a security guarantee.
- Ruff lint and formatting checks passed.
- The official **HA 2026.10.2 hassfest manifest validator** was run against this integration using that tagged source's `manifest.py`, `model.py`, `script/util.py`, and `script/const.py`. It reports one error: missing `documentation`. A full hassfest suite has not passed and is not claimed.
- Dependencies are pinned in `pyproject.toml` and resolved in `uv.lock`. The test plugin is `pytest-homeassistant-custom-component==0.13.373`; tests use its HA fixtures while overriding its mocked-storage fixture to exercise actual temporary disk files.

## Remaining before release / later phases

The owner has not selected a public repository or documentation page. Add its actual URL to the manifest and rerun official validation before release. No placeholder URL, GitHub identity, or published repository was invented. MIT attribution is to SOLBUDDY Access contributors.

Phase 2 still needs owner grant-management APIs, trustworthy device enrollment, service dispatch, audit admission, and concurrent revocation/execution tests. Phase 3 needs secure guest authentication and its enablement gate. Phase 4 adds validated climate adapters. No replay protection, rate limiting, TLS enforcement, or guest sessions are claimed in this endpoint-free foundation.
