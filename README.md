# SOLBUDDY Access

Self-hosted Home Assistant integration foundation for temporary, revocable guest access to selected lights and climate devices.

**Status: Phase 2 backend implemented. Owner grant-management APIs are available; guest endpoints remain disabled. Device execution is internal and test-only until secure guest authentication is implemented. This is a development build, not a usable guest-access release.**

The backend milestone is tested: a 72-hour grant for one selected light denies other entities and actions. The initial enrollment adapter accepts individual Hue v2 physical lights only; groups, templates, and unknown implementations are rejected. Tests use synthetic device fixtures with real HA registries and service dispatch; a real bridge/device has not been exercised. No Home Assistant account or homeowner token is given to guests.

## Documentation

- [Architecture and proposed repository](docs/architecture.md)
- [Grant model and policy semantics](docs/data-model.md)
- [API and authentication proposal](docs/api.md)
- [Threat model, security controls, and test plan](docs/security.md)
- [Incremental implementation roadmap](docs/roadmap.md)
- [Contributor and agent instructions](AGENTS.md)
- [Phase 1 implementation and validation](docs/phase-1.md)
- [Phase 2 implementation and API examples](docs/phase-2.md)

The proposal uses a Home Assistant config entry, versioned native storage, authenticated administrative WebSocket commands, and a fixed device-action adapter. A separate guest credential never authenticates to Home Assistant's general APIs.

SOLBUDDY Access is independent of HomeBuddy, with possible future integration. Solana identity, on-chain credentials, and $SBUD features are outside v0.1. Neither cryptocurrency nor cloud infrastructure is required.

## Implemented

- Owner-only singleton setup flow and typed runtime with unload handling.
- Immutable light grant models and a pure default-deny permission evaluator.
- Versioned HA storage, serialized writes, disk read-back verification, and failure handling.
- Strict schema checks and restart persistence of policies and revocation.
- Owner-only create/list/get/check/revoke WebSocket commands, with current-user checks on each request.
- Server-resolved device bindings, fixed internal light execution, audit admission, and serialized revocation/execution.
- Deny-only guest authenticator; no guest route, execute command, invitation, session, or integration HA service.
- MIT license, pinned development dependencies, and tests using HA fixtures with actual temporary disk storage.

Climate policy support and guest execution access remain in later phases. Policy preview results are never authentication or dispatch authority.

## Development

Target and tested baseline: Home Assistant **2026.10.2**, Python **3.14.2**. Other HA versions have not been tested. With [uv](https://docs.astral.sh/uv/) installed:

```sh
uv sync --locked --group dev
uv run --locked pytest
uv run --locked ruff check custom_components tests
uv run --locked ruff format --check custom_components tests
```

Tests include a temporary loopback HTTP server. A sandbox must permit localhost sockets for that test.

For a disposable development HA installation, copy `custom_components/solbuddy_access` into the configuration directory's `custom_components` folder, restart HA, and add SOLBUDDY Access under Settings → Devices & services while signed in as the owner. Use the [owner WebSocket API examples](docs/phase-2.md) to manage grants. There are no custom management screens or guest controls yet. Removing the config entry retains storage for manual recovery; re-adding creates new empty storage and does not reactivate old grants.

## Repository and validation

Repository: [FilipposPirpilidis/solbuddy-access](https://github.com/FilipposPirpilidis/solbuddy-access). The manifest and Python project metadata use this repository's README for documentation. The official HA 2026.10.2 manifest validator now passes. This is a manifest check, not a claim of complete hassfest or release certification. The codeowners list remains empty until maintainers are declared.

Approved defaults remain owner-only administration, immutable grants, a single instance, 15-minute maximum guest sessions in the future authentication phase, and MIT licensing. Phase 3 has not started.
