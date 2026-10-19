# Wallet access setup — 0.1.0.dev6

Wallet grants require all three: **owner approval of the exact wallet, a signature from that wallet, and at least US$2 of SBUD at a fresh server-verified price**. Guest access and wallet access both default off. Upgrading does not enable them. Ordinary invitation-only grants remain a separate owner choice.

## Install and enable deliberately

1. Copy the entire updated `custom_components/solbuddy_access` folder into Home Assistant's configuration directory, replacing the old integration folder, and restart Home Assistant. Include the new `www` directory. Do not add an integration block to `configuration.yaml`.
2. Set up a working HTTPS address with a browser-trusted certificate. Direct TLS and the documented single trusted proxy are supported; see [transports](transports.md). Wallet pages and signatures require HTTPS, including on your LAN. Existing local HTTP device commands remain available when explicitly enabled. An HTTPS page will not call the HTTP endpoint.
3. Optionally configure providers using `solbuddy_access_wallet.yaml` next to `configuration.yaml`. This is a separate file, not an include inside `configuration.yaml`:

   ```yaml
   rpc_url: !secret solbuddy_rpc_url
   jupiter_api_key: !secret solbuddy_jupiter_api_key
   ```

   Add those values to HA's `secrets.yaml`. The RPC must be a Solana mainnet HTTPS endpoint. If the file is absent, the integration uses the public mainnet RPC and requests Jupiter without a key. Public providers may rate-limit or require authentication; failures deny login. Jupiter documents API-key authentication, so configure a key for reliable operation. Reload the integration after changing this file. Provider keys never go to the browser; the RPC provider can see queried wallet addresses.
4. Open HA **through the configured HTTPS address**, signed in as its owner. Go to Settings → Devices & services → SOLBUDDY Access → Configure. Set the exact HTTPS origin (scheme, host and optional port, without a path), configure any proxy peer, then explicitly enable guest access and wallet access. Keep them disabled until you are ready to test. Enabling wallet access from local HTTP is rejected.

## Approve and invite a guest

At your HTTPS Home Assistant address, open this path in a normal browser tab:

```text
/api/solbuddy_access/v1/wallet/owner-ui
```

For example, append that path to your own `https://ha.example` address. The UI is bundled locally; no CDN scripts or browser storage are used.

- Enter a Home Assistant access token belonging to the **owner**, not another administrator. You can create a long-lived access token in your HA profile's Security tab. Keep this token private, revoke it when no longer needed, and never send it to a guest.
- Enter a guest name, verify their full Solana wallet address, select the exact reviewed Hue v2 physical light by entity ID, and choose the grant duration. This screen approves turn-on and turn-off only. Other device implementations and climate remain unsupported.
- Choose **Approve wallet and create grant**, then **Generate invitation**. Transfer the invitation privately; it expires after five minutes and is single-use. Reissuing one invalidates existing credentials for that grant.
- Clear the owner token when finished. The owner can inspect grants and revoke them on this page. Changing the wallet requires revoking and creating a new grant.

Send the guest the HTTPS address with this path, plus their invitation separately:

```text
/api/solbuddy_access/v1/wallet/ui
```

The guest pastes the invitation, chooses **Phantom**, **Solflare**, or **Trust Wallet**, and signs the displayed login message using the approved account. No transfer, transaction, staking, token approval, seed phrase, or private key is requested. An unapproved wallet cannot sign in even if it holds enough coins. Successful login displays the permitted controls and session expiry.

## Freshness and session rules

The pinned mint is `ERAMuCbBAfHhxNCEb2ZJgf9rLJ4KBbvY1bD9dzHgpump` on Solana mainnet, Token-2022, six decimals. The server verifies mainnet genesis and mint properties, sums distinct finalized token accounts owned by the approved wallet, and values the raw balance using Jupiter Price V3 and Decimal arithmetic. Holdings worth exactly US$2 qualify; values below it do not.

- Price observations must be **at most 300 seconds old**, using the Jupiter source block's time from Solana RPC. A fresh HTTP response containing an old price is rejected. Future, missing, invalid or nonfinite observations are rejected.
- Finalized balance observations must be at most 60 seconds old. Eligibility evidence expires after 30 seconds and is rechecked before session creation, including after audit IO. Provider work has a 12-second total timeout and bounded responses.
- There is no stale-price fallback, hard-coded coin quantity, browser-supplied price, or grace threshold. Thin trading may prevent sign-in frequently. The read-only October 19 research found a price over 17 hours old; that observation is rejected.
- Sessions last at most 15 minutes and never beyond grant expiry. **Sign and renew session** requires a new signature and fresh eligibility checks. Failed renewal does not extend the existing session. A balance drop or pricing outage takes effect at renewal or expiry, not immediately during an already issued session. Owner revocation invalidates it immediately for subsequent authorization.
- Challenges expire after two minutes and bind the wallet, installation, grant, HTTPS origin, purpose and nonce. Replay and the old invitation-only login/renewal paths cannot bypass wallet requirements.
- Restarting, reloading, disabling guest access or revoking invalidates volatile credentials. Wallet grants remain stored, with no private keys, signatures, invitations or session tokens persisted.

## Compatibility and testing limits

Connectors implement Wallet Standard discovery and selected injected providers for Phantom, Solflare and Trust Wallet. Use software accounts supporting raw Solana Ed25519 message signing. Unsupported formats/accounts fail closed. Multiple extensions are selected by name; no arbitrary default provider or transaction fallback is used.

Automated adapter tests cover all three wallets with synthetic providers and real Ed25519 signatures; HA HTTPS tests exercise owner approval, invitation, signed login and device dispatch. Actual extension versions, phone wallet browsers, and real lights still require manual testing. Mobile QR/WalletConnect relay and app-switch deep-link flows are not included. A phone wallet browser works only if it exposes a supported provider; wallet brand alone does not guarantee every mobile connection mode.

The owner token remains in page memory until cleared/closed. Guest credentials likewise remain in memory; reloading the page requires a new invitation. **Forget session** clears this browser's reference; use owner revocation to invalidate it server-side. Avoid shared devices. The standalone page cannot be embedded in an iframe.
