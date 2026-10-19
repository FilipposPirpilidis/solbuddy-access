# Wallet access — 0.1.0.dev9

SOLBUDDY now appears in the Home Assistant sidebar and uses your existing HA login. There is no owner-token field and no second proxy/origin configuration. Guest and wallet access both default off. Only the active HA owner can administer grants; other administrators are denied server-side.

## Update and first test

1. Replace the complete `custom_components/solbuddy_access` folder, including `www`, then restart Home Assistant. Refresh the HA browser page. Do not add anything to `configuration.yaml` for SOLBUDDY.
2. For the free keyless setup, leave `solbuddy_access_wallet.yaml` absent. SOLBUDDY uses public Solana mainnet RPC and Jupiter Price V3. Rate limits or outages deny login; no paid subscription is required by the integration.
3. Open HA through your existing HTTPS address and click **SOLBUDDY Access** in the sidebar. This opens `/solbuddy-access` and uses your current HA session automatically. The old `/api/solbuddy_access/v1/wallet/owner-ui` link redirects to this panel. If HA's external URL is not configured, this authenticated owner visit automatically remembers the HTTPS origin. Anonymous visits cannot set it.
4. Follow **Configure guest and wallet access** to the integration options and explicitly enable both switches when ready to test. They remain off unless you enable them. There are no proxy-IP, origin, or subnet fields. Reloading invalidates existing credentials.
5. Return to the panel and click **Refresh**. Enter a guest name and the exact approved Solana public wallet address. Choose a supported light from the list, turn-on and/or turn-off permission, and a duration in minutes. Click **Approve and create access**, then **Generate invitation**.
6. Share the guest HTTPS page link shown in the panel and the invitation privately. Invitations expire after five minutes and can be used once. Generating a replacement invalidates existing credentials for that grant.
7. On the guest HTTPS page, choose Phantom, Solflare or Trust and sign with the approved account. No payment, staking, transaction, token approval or private key is requested. Test the permitted controls, then revoke from the owner panel and confirm subsequent commands fail.

The panel currently lists only individual physical Hue v2 lights. It explains when no supported devices exist. Switches, eWeLink, templates, groups, climate and other integrations are not enabled by this change. Grants still cover one explicitly selected light. Owner approval binds one immutable wallet; changing it requires revoking and replacing the grant.

## Local HTTP and remote HTTPS

HA's existing network adapters, internal/external URLs and trusted proxy middleware determine allowed connections. The default local hostname `http://homeassistant.local:8123` and private HA adapter IPv4 addresses are recognized. A previously configured HTTPS origin also remains recognized. The owner can discover the remote origin simply by opening the sidebar panel through that HTTPS address.

For this installation:

- Owner panel: `https://fphomebuddy.uk/solbuddy-access` or `http://homeassistant.local:8123/solbuddy-access`.
- Wallet signing: `https://fphomebuddy.uk/api/solbuddy_access/v1/wallet/ui`.
- Local guest controls: `http://homeassistant.local:8123/api/solbuddy_access/v1/wallet/ui`.

The local guest page links to HTTPS for wallet signing. After signing in there, choose **Move session to another HA address**. Paste the one-time code into **Use session here** on the local guest page. This is an explicit transfer, not a token in a URL or a mixed-content browser request. The code expires in two minutes; claiming it invalidates the previous session and preserves the original expiry. It cannot bypass wallet eligibility or extend access. To renew, transfer back to HTTPS, connect the approved wallet and sign again, or obtain a new invitation. The UI stores no credentials in localStorage/sessionStorage. Reloading a page loses its credentials.

Local HTTP is unencrypted. Enabling guest access now permits direct local HTTP from detected private HA networks as well as recognized HTTPS. Remote/proxy requests never receive the LAN exception, even if the proxy itself is on your LAN. Do not expose the plaintext HA port directly to the internet. Network detection failure denies local guest requests while HTTPS and HA owner management remain usable.

A cloudflared process on a separate Raspberry Pi works through HA's existing `use_x_forwarded_for` / `trusted_proxies` handling. SOLBUDDY no longer requires copying the Pi's IP into a separate list and accepts HA-validated forwarding chains. Forwarded requests must still represent HTTPS. CF-specific headers alone grant no trust. Your HA/tunnel configuration must already forward the original host and scheme correctly; this integration does not modify HA's HTTP configuration or fix arbitrary tunnel overrides. Nabu Casa Remote UI remains outside the tested transport support.

## Wallet and price rules

The fixed mint is `ERAMuCbBAfHhxNCEb2ZJgf9rLJ4KBbvY1bD9dzHgpump`, on Solana mainnet, Token-2022, six decimals. Login and renewal require owner approval, an invitation/session, an exact one-time Ed25519 signature, finalized owned token holdings, and a server-calculated value of at least US$2. The wallet balance is not spent or locked.

Jupiter observations older than 300 seconds are rejected using the source block's time, even if the HTTP response was just fetched. Balance observations must be at most 60 seconds old. Missing, future, nonfinite or malformed data fails closed. No stale-price fallback or fixed token quantity exists. Thin trading can make login unavailable even with sufficient holdings. Paying for a provider does not make an old price fresh.

Sessions last at most 15 minutes and never beyond grant expiry. Renewal requires a new signature and fresh eligibility. A failed renewal does not extend an existing session. Balance drops are detected at renewal; owner revocation is immediate at subsequent authorization. Session transfers never extend that window. Restart/reload/disable/revoke invalidates volatile credentials and transfer codes. Wallet bindings and grant/revocation records persist; secrets, signatures and usable credentials do not.

Optional provider overrides still use a separate `solbuddy_access_wallet.yaml` beside `configuration.yaml`, with `rpc_url` and `jupiter_api_key` supporting HA `!secret`. Keys stay server-side; RPC providers observe queried public wallets. Leave the file absent for keyless operation.

## Validation limits

Automated tests use real HA HTTP/auth/forwarded middleware, real Ed25519 signatures and synthetic provider/device data. Browser tests exercise the native panel and local transfer UI with synthetic API responses. Actual extension versions, your live tunnel, qualifying real wallet holdings and physical devices still need installation testing. Mobile QR/deep links are not implemented; mobile wallet browsers require compatible injected/Wallet Standard providers. No claim is made that a local automated test has deployed or validated your production HA instance.

## Freshness diagnostics (dev8)

After a valid wallet proof, a failed freshness check now identifies **price**, **balance**, or both, with each failing observation's age and allowed maximum. For example: “Price observation is stale: 17h 16m old (maximum 5m)” or “Balance observation is stale: 1m 32s old (maximum 1m)”. Ages describe source observations, not HTTP fetch time, and reflect the server check time rather than a live counter. Displayed seconds round away from zero; authorization uses the exact age.

Future timestamps are labeled as ahead of the server clock and remain rejected. If both observations are fresh but the short-lived eligibility check expires during processing, the message instead says the eligibility check expired. No new session is issued in any of these cases. The US$2 minimum and freshness thresholds are unchanged. Error responses contain only status/age/limit metadata, never wallet balances, addresses, signatures, provider keys or raw provider responses.

## Approved-access preview (dev9)

After the approved wallet signs a valid challenge, an eligibility failure now shows the permitted entity IDs, actions, and **grant expiry** alongside “Wallet verified”. The existing price/balance diagnostic explains why controls are disabled. No session token is issued. Device commands, renewal, transfer and session-permission requests remain disabled until eligibility succeeds. If both checks pass, normal guest controls become available.

This is a read-only snapshot at verification time, not a live authorization or session. It can remain visible after later owner changes; every actual operation still requires a live eligible session and current grant checks. Invalid signatures, expired/replayed proofs, revoked/expired grants and invalid credentials receive no preview. Retry **Connect and sign in** with a fresh signature while the invitation is valid; after its five-minute expiry, obtain a new invitation. The US$2 requirement and fresh-price limits are unchanged.
