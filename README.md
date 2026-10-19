# SOLBUDDY Access

Self-hosted Home Assistant integration foundation for temporary, revocable guest access to selected lights and climate devices.

**Status: Wallet approval, Phantom/Solflare/Trust signing connectors, and fresh US$2 SBUD eligibility are implemented in 0.1.0.dev6. Wallet access defaults off. Phase 3 guest authentication and sessions are implemented and security-tested. Guest access defaults off and requires explicit owner configuration. Local HTTP is a separate opt-in; remote HTTPS supports direct TLS or one trusted proxy. This is a development build; real-device and release-readiness validation remain outstanding.**

The backend milestone is tested: a 72-hour grant for one selected light denies other entities and actions. The initial enrollment adapter accepts individual Hue v2 physical lights only; groups, templates, and unknown implementations are rejected. Tests use synthetic device fixtures with real HA registries and service dispatch; a real bridge/device has not been exercised. No Home Assistant account or homeowner token is given to guests.

## Documentation

- [Architecture and proposed repository](docs/architecture.md)
- [Grant model and policy semantics](docs/data-model.md)
- [API and authentication](docs/api.md)
- [Threat model, security controls, and test plan](docs/security.md)
- [Incremental implementation roadmap](docs/roadmap.md)
- [Contributor and agent instructions](AGENTS.md)
- [Phase 1 implementation and validation](docs/phase-1.md)
- [Phase 2 implementation and API examples](docs/phase-2.md)
- [Phase 3 guest enablement, protocol, and client workflow](docs/phase-3.md)
- [Local HTTP and remote HTTPS setup](docs/transports.md)
- [Wallet approval, providers, and guest sign-in setup](docs/wallet-access.md)

The integration uses a Home Assistant config entry, versioned native storage, authenticated administrative WebSocket commands, and a fixed device-action adapter. A separate guest credential never authenticates to Home Assistant's general APIs.

SOLBUDDY Access is independent of HomeBuddy, with possible future integration. Optional owner-approved Solana wallet grants require at least US$2 of SBUD, fresh Jupiter pricing, and mainnet RPC connectivity. Ordinary invitation-only grants require neither cryptocurrency nor external providers.

## Implemented

- Owner-only singleton setup flow and typed runtime with unload handling.
- Immutable light grant models and a pure default-deny permission evaluator.
- Versioned HA storage, serialized writes, disk read-back verification, and failure handling.
- Strict schema checks and restart persistence of policies and revocation.
- Owner-only create/list/get/check/revoke WebSocket commands, with current-user checks on each request.
- Server-resolved device bindings, fixed internal light execution, audit admission, and serialized revocation/execution.
- Single-use invitations, scoped rotating sessions, replay protection, rate limits, and configurable local HTTP / remote HTTPS guest control.
- Owner-only options; guest access defaults off and credentials are invalidated on reload/restart/revocation.
- Local HTTP detects allowed private networks from Home Assistant automatically; no manual subnet entry.
- Owner-approved immutable wallet grants, HTTPS wallet pages, one-time Ed25519 challenges, and fresh eligibility at login and renewal.
- MIT license, pinned development dependencies, and tests using HA fixtures with actual temporary disk storage.

Climate policy support remains in a later phase. Policy preview results are never authentication or dispatch authority.

## Development

Target and tested baseline: Home Assistant **2026.10.2**, Python **3.14.2**. Other HA versions have not been tested. With [uv](https://docs.astral.sh/uv/) installed:

```sh
uv sync --locked --group dev
uv run --locked pytest
uv run --locked ruff check custom_components tests examples
uv run --locked ruff format --check custom_components tests examples
node --test tests/frontend/*.test.mjs
```

Tests include temporary loopback HTTP and verified HTTPS servers. A sandbox must permit localhost sockets.

For a disposable development HA installation, copy `custom_components/solbuddy_access` into the configuration directory's `custom_components` folder, restart HA, and add SOLBUDDY Access under Settings → Devices & services while signed in as the owner. Use the [owner WebSocket API examples](docs/phase-2.md) to manage grants. For guest enablement and the minimal interactive client, follow the [transport setup](docs/transports.md) and [Phase 3 workflow](docs/phase-3.md). For the bundled owner and guest wallet pages, follow the [wallet setup guide](docs/wallet-access.md). Removing the config entry retains storage for manual recovery; re-adding creates new empty storage and does not reactivate old grants.

## Repository and validation

Repository: [FilipposPirpilidis/solbuddy-access](https://github.com/FilipposPirpilidis/solbuddy-access). The manifest and Python project metadata use this repository's README for documentation. The official HA 2026.10.2 manifest validator now passes. This is a manifest check, not a claim of complete hassfest or release certification. The codeowners list remains empty until maintainers are declared.

Approved defaults remain owner-only administration, immutable grants, a single instance, 15-minute maximum guest sessions, and MIT licensing. Phase 3 is implemented; Phase 4 climate and Phase 5 release readiness remain outstanding.
