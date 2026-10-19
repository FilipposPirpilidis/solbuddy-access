# SOLBUDDY Access development instructions

## Current scope

The user requested precise wallet freshness diagnostics: identify stale price versus stale balance and show observation age. Preserve the US$2 gate, 300-second price maximum, 60-second balance maximum, future-observation rejection, and default-off guest/wallet access. The user authorized committing and pushing the freshness diagnostics fix. Deployment remains outside scope. Return only safe age/status metadata after valid wallet proof, never balances, credentials, wallets, raw provider data or keys.

## Architecture

- Domain: `solbuddy_access`; package: `custom_components/solbuddy_access/`.
- Local, self-hosted, privacy-first. Ordinary grants need no cloud or blockchain service; optional wallet grants require mainnet RPC and fresh Jupiter pricing. Keep both access flags default-off.
- Use a single UI-created config entry and typed runtime data. Use native versioned `Store` persistence with explicit atomic writes and awaited security-critical saves.
- Separate models, storage, grant lifecycle, authentication, policy evaluation, and HA device execution. All transports call the same application service.
- Do not use a polling coordinator for local grant state. Use lifecycle timers for notifications and authoritative request-time expiration checks.
- Administration requires a currently active HA owner. Never treat a network location, a missing user context, or an automation as an owner.
- Guest credentials must not authenticate to the HA REST or WebSocket API. Register guest transport only after the tested source gate passes and an owner explicitly enables it.

## Security invariants

- Deny by default. Only individually approved light/climate entities and enumerated actions are eligible. No arbitrary service, template, script, scene, area, device, label, wildcard, batch, or group targets.
- Locks, cameras, alarms, and every other domain are prohibited, including indirect wrappers identified during entity enrollment. Never add lock access to ordinary grants.
- Check current session, grant lifetime, revocation, entity binding, action permission, parameter limits, capability, and storage health immediately before dispatch.
- Grants are immutable except revocation. Never trust client-supplied identity, status, owner IDs, or authorization results.
- Serialize authorization/dispatch and revocation using a documented gate. Test both race orderings. Do not claim already dispatched physical operations can be canceled.
- Use strict schemas; reject unknown fields, booleans masquerading as numbers, nonfinite values, and out-of-range values. Do not silently clamp.
- Never log tokens, invitations, headers, raw request bodies, wallet secrets, HA credentials, or guest identifiers. Do not persist plaintext guest credentials.
- Fail closed on corrupted storage, migration failure, uncertain identity/capabilities, audit admission failure, or clock integrity failure. Revocation remains allowed during faults.
- No cryptography invented here. Wallet signatures authenticate a principal; local policy remains authoritative.

## Coding and development

- Use modern typed Python, async HA APIs, small modules, and immutable validated model objects. Phase 1 targets Python 3.14.2 and Home Assistant 2026.10.2 with pytest-homeassistant-custom-component 0.13.373. Follow that release's schema conventions rather than copying moving development-branch examples.
- Run `uv sync --locked --group dev`, `uv run --locked pytest`, and Ruff check/format checks. The HTTP test requires loopback sockets. Preserve the lockfile when changing dependencies.
- Native Store in the pinned HA release can swallow write errors and automatically accept unknown minor versions. Keep explicit envelope validation and independent disk verification; tests must exercise actual Store IO, not only mocks.
- Setup authenticates the active owner through HA's current HTTP request and re-resolves the user at each flow step. Do not trust flow context/user input as owner identity.
- Store only light policies; climate remains denied until Phase 4. There is no WebSocket execute command or integration HA service. Guest execution requires a server-bound, live session rechecked at final dispatch.
- Invitations and sessions use distinct 256-bit random credentials and only SHA-256 digests in volatile memory. Invalidate on revocation, replacement, restart, reload, and disabling access. Never persist credentials.
- Use an owner-authenticated HTTP invitation endpoint, not a secret-bearing WebSocket response: the pinned HA WebSocket debug logger logs outgoing message bodies.
- Guest origins come from HA internal/external URLs, legacy configured URLs, and an HTTPS origin observed in an authenticated owner panel request. Never learn an origin from anonymous requests. Local HTTP requires an enabled private HA adapter network and a recognized local HA host; trusted proxy peers never receive the local exemption. Use HA's existing trusted_proxies and validated forwarded client/scheme, including parsed chains; do not trust CF headers as independent authentication. Reject cross-origin requests and plaintext forwarded traffic. Wallet proof remains HTTPS-only. One-time transfer codes must preserve session expiry, be volatile, expire after two minutes, reject replay, and invalidate the previous session upon claim. Native owner calls use HA's authenticated HTTP client, never secret-bearing WebSocket responses.
- Use the selected GitHub repository's README as the documentation URL. Report the exact validation performed; do not equate a manifest-only check with the full hassfest suite.
- Enrollment must resolve registry/config-entry/device identity server-side and verify an explicitly reviewed physical light implementation. Never accept registry IDs or trusted-device flags from API input.
- Do not block the event loop. Use HA lifecycle helpers and unload callbacks; clean up timers and in-memory sessions.
- Use pytest for pure policy tests and real HA fixtures for integration behavior. Use Ruff formatting/linting and applicable hassfest checks. Do not substitute mocked HA behavior for all integration tests.
- Cover every denial path listed in `docs/security.md`, persistence faults, and concurrent revoke/execute. Every security bug gets a regression test.
- Keep protocol and storage schema versions explicit. Migrations must never widen permissions or erase revocations.
- Document behavior, limitations, and validation evidence. Do not claim checks passed unless run. Use synthetic data only in examples and fixtures.
- Never commit credentials or local HA storage. Do not expose a remote endpoint, publish, or deploy as part of local development without authorization.
- Solana wallet approval and SBUD eligibility UI are now authorized. Smart-lock workflows, payments, staking, and climate support remain outside scope.

## Phase 3 validation baseline

On 2026-10-19, the full suite passed 191 tests with 92% integration coverage; Ruff and the official HA 2026.10.2 manifest-only validator passed. The authentication/HTTPS/options suite passed before `GUEST_TRANSPORT_VERIFIED` was opened. Preserve default-off owner options and credential invalidation. See `docs/phase-3.md` for protocol, client workflow, supported direct-TLS topology, and remaining real-device/full-hassfest release checks.

## Dual-transport validation baseline

Local HTTP / single-hop proxy HTTPS follow-up: 229 tests passed with 92% integration coverage, plus Ruff and manifest-only validation. See `docs/transports.md` for owner setup, exact proxy header contract, plaintext limitations, and unsupported multi-hop/Cloud transports. Guest access and local HTTP remain default-off.

## Automatic network detection validation

Version 0.1.0.dev5: full regression suite passed 235 tests; the additional options error/removed-field test also passed (236 total). Ruff, locked dependency sync, manifest-only validation, and translation parity passed. Network detection uses HA adapter state and preserves existing manual restrictions until the owner saves options.

## Wallet implementation validation

Version 0.1.0.dev6: 287 Python tests passed with 91% integration coverage; seven Node wallet-connector tests passed for Phantom, Solflare and Trust. Ruff, locked offline dependency sync, JS syntax checking, English translation parity, and the official HA 2026.10.2 manifest-only validator passed. A read-only public RPC call verified the full mainnet genesis hash. Tests cover real Ed25519 signatures, HTTPS owner/guest flows and renewal, alternate-path denial, replay/revocation races, exact US$2 arithmetic, stale/future prices, provider errors, and HA `!secret` loading. See docs/wallet-access.md for setup and limits. Actual extensions, mobile browsers, live qualifying holdings, and physical devices still need manual validation; mobile QR/deep links are not implemented. Access stays default-off; no push or deployment occurred.


## Native owner panel and HA-managed connections validation

Version 0.1.0.dev7: full Python regression suite passed 307 tests with 91% coverage. After the final URL preference adjustment, all 24 targeted automatic-connection/handoff tests passed, including one additional regression (308 unique Python tests). Seven wallet connector tests and three isolated headless Chrome UI flows passed. Ruff, locked dependency sync, JS syntax, English translation parity and HA manifest-only validation passed. The dev dependency now includes the exact frontend required by HA 2026.10.2 so panel registration/setup tests use real frontend setup. The native panel reuses hass.callApi, lists reviewed lights/actions, and remains available while guest access is off. Cloudflare-style chains are tested through real HA middleware; the user's live tunnel and real devices are not deployed or verified. Both access flags default off. Validation preceded the user-authorized commit and push. See docs/wallet-access.md for current setup and tests/frontend/browser-check.mjs for reproducible synthetic UI flows.

## Freshness diagnostics validation

Version 0.1.0.dev8: 316 Python regression tests, 11 Node tests and four isolated Chrome browser flows passed. Ruff, locked dependency sync and HA manifest-only validation passed. HTTP tests verify age/status details after a valid signature, no session issuance on stale evidence, and no credentials/addresses in diagnostic responses or captured logs. Exact age limits, simultaneous stale observations, future observations, and expired evidence remain denied. US$2 valuation, default-off flags and provider selection are unchanged. Validation preceded the user-authorized commit and push. No production update is included.
