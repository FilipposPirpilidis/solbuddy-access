# SOLBUDDY Access development instructions

## Current scope

The user approved Phase 2: implement owner-only create/list/get/check/revoke WebSocket commands, trusted single-light enrollment, internal fixed light execution, durable auditing, and concurrent revoke/execute defenses and tests. Preserve the Phase 1 foundation. Guest authentication stays deny-only; do not register guest endpoints or expose any execute command. Session issuance, replay protection, guest transport, and climate adapters remain later phases. The selected repository is https://github.com/FilipposPirpilidis/solbuddy-access. The user explicitly authorized committing and pushing the Phase 2 implementation there, with guest endpoints disabled. This does not authorize deployment or enabling guest access.

## Architecture

- Domain: `solbuddy_access`; package: `custom_components/solbuddy_access/`.
- Local, self-hosted, privacy-first; no required cloud, wallet, token, or blockchain service.
- Use a single UI-created config entry and typed runtime data. Use native versioned `Store` persistence with explicit atomic writes and awaited security-critical saves.
- Separate models, storage, grant lifecycle, authentication, policy evaluation, and HA device execution. All transports call the same application service.
- Do not use a polling coordinator for local grant state. Use lifecycle timers for notifications and authoritative request-time expiration checks.
- Administration requires a currently active HA owner. Never treat a network location, a missing user context, or an automation as an owner.
- Guest credentials must not authenticate to the HA REST or WebSocket API. Keep guest transport unregistered until authentication and security tests pass.

## Security invariants

- Deny by default. Only individually approved light/climate entities and enumerated actions are eligible. No arbitrary service, template, script, scene, area, device, label, wildcard, batch, or group targets.
- Locks, cameras, alarms, and every other domain are prohibited, including indirect wrappers identified during entity enrollment. Never add lock access to ordinary grants.
- Check current session, grant lifetime, revocation, entity binding, action permission, parameter limits, capability, and storage health immediately before dispatch.
- Grants are immutable except revocation. Never trust client-supplied identity, status, owner IDs, or authorization results.
- Serialize authorization/dispatch and revocation using a documented gate. Test both race orderings. Do not claim already dispatched physical operations can be canceled.
- Use strict schemas; reject unknown fields, booleans masquerading as numbers, nonfinite values, and out-of-range values. Do not silently clamp.
- Never log tokens, invitations, headers, raw request bodies, wallet secrets, HA credentials, or guest identifiers. Do not persist plaintext guest credentials.
- Fail closed on corrupted storage, migration failure, uncertain identity/capabilities, audit admission failure, or clock integrity failure. Revocation remains allowed during faults.
- No cryptography invented here. Future identity adapters authenticate a principal; local policy remains authoritative.

## Coding and development

- Use modern typed Python, async HA APIs, small modules, and immutable validated model objects. Phase 1 targets Python 3.14.2 and Home Assistant 2026.10.2 with pytest-homeassistant-custom-component 0.13.373. Follow that release's schema conventions rather than copying moving development-branch examples.
- Run `uv sync --locked --group dev`, `uv run --locked pytest`, and Ruff check/format checks. The HTTP test requires loopback sockets. Preserve the lockfile when changing dependencies.
- Native Store in the pinned HA release can swallow write errors and automatically accept unknown minor versions. Keep explicit envelope validation and independent disk verification; tests must exercise actual Store IO, not only mocks.
- Setup authenticates the active owner through HA's current HTTP request and re-resolves the user at each flow step. Do not trust flow context/user input as owner identity.
- Store only light policies; climate remains denied until Phase 4. Phase 2 registers owner management commands only, with no execute command, guest route, or integration HA service.
- Use the selected GitHub repository's README as the documentation URL. Report the exact validation performed; do not equate a manifest-only check with the full hassfest suite.
- Enrollment must resolve registry/config-entry/device identity server-side and verify an explicitly reviewed physical light implementation. Never accept registry IDs or trusted-device flags from API input.
- Do not block the event loop. Use HA lifecycle helpers and unload callbacks; clean up timers and in-memory sessions.
- Use pytest for pure policy tests and real HA fixtures for integration behavior. Use Ruff formatting/linting and applicable hassfest checks. Do not substitute mocked HA behavior for all integration tests.
- Cover every denial path listed in `docs/security.md`, persistence faults, and concurrent revoke/execute. Every security bug gets a regression test.
- Keep protocol and storage schema versions explicit. Migrations must never widen permissions or erase revocations.
- Document behavior, limitations, and validation evidence. Do not claim checks passed unless run. Use synthetic data only in examples and fixtures.
- Never commit credentials or local HA storage. Do not expose a remote endpoint, publish, or deploy as part of local development without authorization.
- Solana, tokens, custom panels, and smart-lock workflows require separate future scope; do not implement them speculatively.
