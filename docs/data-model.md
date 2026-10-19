# Grant and policy model

Examples below illustrate the original target design. Phase 2 serializes grant schema v2: policies are a list with explicit `entity_id`, registry ID, config-entry ID, device ID, and entity unique ID. Bindings come from the server, never request fields. The owner API creates exactly one-light grants and the stored collection is capped at 100. Legacy v1 grants load for inspection/revocation but cannot execute without replacement and fresh enrollment. Climate remains denied. See [Phase 2 status](phase-2.md).

## Persistent grant

| Field | Meaning and validation |
| --- | --- |
| `grant_id` | Server-generated random UUID; unique, never an authentication credential |
| `guest_display_name` | Trimmed text, 1–100 characters; never used for authorization |
| `guest_identifier` | Optional namespaced identifier, max 256 characters; inert metadata in v0.1, not proof of wallet ownership |
| `created_by` | Server-derived current HA owner user ID |
| `created_at` | Server UTC timestamp |
| `starts_at`, `expires_at` | Timezone-aware inputs normalized to UTC; `starts_at < expires_at`; expiration must be in the future at creation |
| `revoked_at`, `revoked_by` | Null or server-derived revocation metadata; irreversible |
| `policies` | Nonempty mapping of individually approved entity bindings to permitted action policies |
| `schema_version` | Explicit data version, with conservative migrations |

Proposed resource bounds: 100 live/pending grants, 32 entities per grant, 30-day maximum grant duration, and bounded archived history. These are configurable by future owner-only options within hard resource ceilings; guests cannot change them. A 72-hour grant is an elapsed UTC duration, unaffected by local daylight-saving changes.

Status is returned as `revoked` if revoked, otherwise `expired` when `now >= expires_at`, `pending` when `now < starts_at`, else `active`. Do not persist a mutable `active` boolean as authority. A grant permits execution only in the half-open interval `[starts_at, expires_at)`.

Each binding records exact `entity_id`, registry entry identity, and backing integration/config-entry identity where available. Missing registry identity, unrecognized forwarding entities, template entities, and group lights are ineligible for the initial milestone. A binding mismatch denies access rather than granting to a replacement entity with the same name. Explicit owner reapproval is required after changes.

## Example: one light for 72 hours

```json
{
  "schema_version": 1,
  "grant_id": "593466a0-8387-4de0-b386-d44649fd886f",
  "guest_display_name": "Guest A",
  "guest_identifier": null,
  "created_by": "example-owner-id",
  "created_at": "2026-10-19T12:00:00Z",
  "starts_at": "2026-10-19T12:00:00Z",
  "expires_at": "2026-10-22T12:00:00Z",
  "revoked_at": null,
  "revoked_by": null,
  "policies": {
    "light.guest_room": {
      "registry_id": "example-registry-id",
      "config_entry_id": "example-device-integration-id",
      "actions": ["turn_on", "turn_off", "set_brightness"],
      "brightness_min": 20,
      "brightness_max": 180,
      "turn_on_brightness": 100
    }
  }
}
```

## Action semantics

| Domain/action | Request parameters | Enforcement and dispatch |
| --- | --- | --- |
| `light.turn_on` | None | If bounded brightness is configured, send owner-chosen `turn_on_brightness` within bounds; otherwise on/off-only operation |
| `light.turn_off` | None | Exact single light; no extra service data |
| `light.set_brightness` | Integer `brightness` | Require brightness support and configured inclusive limits within 1–255; dispatch fixed `light.turn_on` with brightness |
| `climate.turn_on` | None | Require explicit turn-on capability; use owner-selected approved non-off mode and bounded target when supported, avoiding unapproved restored settings |
| `climate.turn_off` | None | Require explicit turn-off capability; permission is distinct from other actions |
| `climate.set_hvac_mode` | Enum `hvac_mode` | Require intersection of owner-approved modes and currently reported device modes |
| `climate.set_temperature` | Finite numeric `temperature` | Require target-temperature capability; inclusive owner and device limits; validate unit and step |

Every action is separately permitted. Brightness-setting is explicitly an operation that can turn a light on; document that implication when creating the policy. Zero brightness is rejected rather than used to bypass a denied turn-off action. Bounded brightness policies require brightness-capable lights. Plain turn-on must not restore an out-of-policy previous brightness. Color, effects, transitions, relative steps, toggles, and profiles are excluded.

Climate policy contains `allowed_hvac_modes`, `temperature_min`, `temperature_max`, `temperature_unit`, and, when turning on/mode switching is permitted, an approved default target and mode. `off` in a mode request also requires `turn_off`. Policies with unsupported capability combinations are rejected. Normalize temperature once in the explicit stored unit; reject unit changes until owner review and avoid rounding across bounds. Reject booleans, NaN, infinities, strings, target ranges, presets, fan controls, and unknown fields.

Climate devices can restore targets when changing mode. Only support adapters proven to apply the approved mode and target without an unsafe intermediate setting; otherwise deny turn-on/mode changes and expose only independently safe actions. This compatibility work is a Phase 4 gate, not a claim that all HA climate devices behave uniformly. [Climate capabilities](https://developers.home-assistant.io/docs/core/entity/climate/), [light semantics](https://contributors.home-assistant.io/core/entities/light/).

Grants cannot be extended or edited in v0.1. Revoke and replace them. Empty action lists, duplicate entity bindings, unknown actions/domains, and action/domain mismatches are invalid. No global action list may accidentally authorize an action on another entity.

## Ephemeral authentication state

A session contains a random session ID, credential digest, grant ID, issuance time, expiry, monotonic deadline, next request sequence, and in-flight marker. Session expiry is the earlier of 15 minutes from issue or grant expiry. Invitations and sessions exist only in memory; no refresh token is persisted. All are invalid after restart/unload. See [authentication proposal](api.md) for issuance and renewal.

## Wallet policy records

Wallet grants use per-record schema 3, adding a canonical `wallet_address` and the fixed `wallet_policy` identifier `solana-mainnet-sbud-usd2-v1`. This selects exact mainnet SBUD Token-2022 holdings and the US$2 fresh-price policy. Unknown policies are rejected. Existing schema 1/2 grants retain ordinary invitation-only behavior; no migration silently adds wallet access or changes revocations. Wallet bindings cannot be edited. All challenges, signatures and usable credentials are volatile; only the owner-approved wallet binding is persisted. See [wallet access](wallet-access.md).
