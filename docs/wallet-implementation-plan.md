# Owner-approved Solana wallets and US$2 SBUD eligibility

Status: implemented locally in 0.1.0.dev6, following user approval on 2026-10-19. This document preserves the research and design rationale; see [wallet setup and implementation limits](wallet-access.md) for current behavior. Guest and wallet access remain default-off. The user subsequently authorized committing and pushing the wallet and automatic-network-detection implementation. Deployment, transactions, and purchases remain outside scope. Mobile QR/deep-link flows and manual wallet/device certification remain outstanding.

## Verified token and pricing evidence

Read-only verification completed around 2026-10-19 12:54 UTC:

| Property | Observed result |
| --- | --- |
| Network | Solana mainnet, queried via `https://api.mainnet-beta.solana.com` |
| Mint | `ERAMuCbBAfHhxNCEb2ZJgf9rLJ4KBbvY1bD9dzHgpump` |
| On-chain metadata | SOLBUDDY / SBUD |
| Decimals | 6 |
| Program | Token-2022 (`TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb`) |
| Mint/freeze authorities | Both null |
| Observed extensions | metadataPointer and tokenMetadata; metadata authorities null |
| Finalized RPC context slot | 458840404 |
| Jupiter returned USD price | 0.0000031027715789478525 |
| Jupiter price slot | 458553790 |
| Price slot time, verified with RPC getBlockTime | 2026-10-18 19:38:16 UTC |
| Price age at verification | About 17 hours 16 minutes |
| Jupiter reported liquidity | Approximately US$3,180.53 |
| DEX Screener corroboration | Pump.fun pair `72oFDXz4xLMDAFVo35PAoLx2fSRrmTneqQ2xzHjqdodC`; displayed price US$0.000003109; 24h volume US$0.98, one buy |

These are transient observations, not guarantees of value, liquidity, or safety. RPC inspection verifies the exact on-chain account and metadata; the homeowner identifies this mint as the intended coin. No authority status is a security certification.

Jupiter Price V3 is a viable integration candidate and returned this exact mint in a live request. Its response is NOT currently suitable for fresh-price credential issuance: retrieving it now does not make its underlying observation fresh. DEX Screener confirms market availability but not a fresh independent oracle. Both may reflect the same thin market. Do not silently replace an unavailable/stale Jupiter price with DEX Screener's displayed price, a hard-coded token count, or an owner-entered USD value.

At that historical Jupiter price, US$2 was approximately 644,585 SBUD. This is illustrative only, never a fixed eligibility threshold. Proposed price maximum age: five minutes, verified from the source slot via `getBlockTime`, including null/future/invalid-time rejection. Under this rule the observed price would deny issuance and renewal. Thin trading may make the feature unavailable frequently. Implementation may proceed with deterministic test fixtures, but live enablement requires an acceptable fresh-price policy and evidence. Any decision to allow older prices changes the meaning of the dollar gate and needs explicit review.

## Wallet support

Target Phantom, Solflare, and Trust Wallet software wallets. All have documented Solana message-signing capabilities. Use Wallet Standard discovery where available, with a small provider/connector adapter when required. Never select an arbitrary `window.solana` when multiple extensions are installed. Detect the selected account's signing capability and Solana chain support, and reject unsupported modes clearly.

Test desktop browser extensions first; separately test Android/iOS in-wallet browsers and mobile connection paths. Trust Connect documents Solana signing and WalletConnect integration, but those docs do not certify every mobile-wallet/version combination. Mobile QR connections may require a WalletConnect project ID and relay; extension connections should not require that service. Pin packages and bundle assets locally; never load wallet code from arbitrary runtime CDNs.

Use an HTTPS top-level guest page, not a HA iframe. Phantom documents HTTPS or loopback-localhost provider injection; `http://homeassistant.local:8123` is not localhost. Existing local HTTP command support remains available, but a wallet connect button there must not be promised. Keep the browser wallet experience on HTTPS; do not transfer tokens into URLs, localStorage, or cross-origin redirects, and do not make an HTTPS page call an HTTP API as a mixed-content workaround.

## Implementation stages

### 1. Versioned owner-approved grants

Extend the immutable grant schema with a versioned authentication mode (schema 3 plus a fixed wallet policy for wallet grants): existing invitation-only mode or new wallet-and-SBUD mode. New mode pins the wallet's canonical 32-byte public key, Solana mainnet identity, exact mint, decimals/program, and US$2 minimum. The active HA owner chooses the wallet, allowed device/actions, and grant expiry. Wallet replacement requires revoke-and-replace; old sessions stop immediately. Preserve existing grants/revocations without automatically upgrading or weakening them.

Add an owner screen to create these grants and show the full wallet/mint addresses. The wallet address is an identity binding, not arbitrary guest metadata. No paid transactions, staking, transfer approval, or smart contract is required. Existing supported devices remain individual reviewed Hue v2 lights.

### 2. Wallet proof and challenge boundary

Extend the owner-issued invitation flow: a wallet grant's invitation alone cannot create a session. Guest submits it in a header, connects the owner-approved wallet, and requests a bounded one-time challenge. It discloses no other grants. A stolen invitation cannot be claimed by another wallet. Owner approval precedes device access.

Challenge includes installation ID, exact HTTPS domain/URI, mainnet identifier, wallet, grant binding, purpose, random 256-bit nonce, issue time, and two-minute expiry. Use established SIWS/off-chain formats; capability-negotiate supported message formats and verify the complete expected bytes server-side using an established Ed25519 implementation. No transaction-signing fallback. Unknown formats, wrong account, altered fields, wrong origin, reused or expired nonces fail closed.

Consume accepted proof atomically, prevent concurrent replay, cap outstanding challenges (one per grant; maximum 100), and use existing source/global limits. Bound public request sizes and error responses. No raw signatures, invitation strings, wallet addresses, API keys, or challenge bodies in logs. Keep challenges/proofs volatile and discard them on reload/restart/revoke. Add only narrowly scoped challenge/verification routes; no anonymous grant discovery or broad unauthenticated operations.

### 3. Token balance and eligibility adapter

Backend verifies mainnet RPC identity and the mint account/program/decimals. Read finalized token accounts owned by the exact approved wallet and filter by exact mint; support Token-2022 explicitly. Sum raw integer balances across distinct accounts, rather than checking only one associated token account. Reject mismatched ownership/program, frozen/uninitialized accounts, unexpected extensions, invalid amounts, and incomplete responses. Use bounded asynchronous HTTP with timeouts and schema validation. Do not fetch untrusted metadata URIs.

Fetch price server-side from Jupiter V3. Require the exact mint key, matching decimals, finite positive Decimal price, valid recent source slot/time, and complete responses. Do not trust a price supplied by the browser. Compute `Decimal(raw_balance) / 10**6 * usd_price >= Decimal('2.00')`; do not round up or grant grace below $2. Record a safe eligibility reason and observation times, not private balances or signatures in normal logs.

Use an owner-configured HTTPS Solana RPC endpoint and Jupiter API configuration. Public RPC was sufficient for research; production availability/rate limits must be tested. Jupiter documentation specifies an API key despite this read succeeding without one. Store configured secrets server-side with HA credential handling/redaction and never expose them in frontend assets. Explain that RPC providers can observe queried wallet addresses and that wallet eligibility requires internet connectivity.

### 4. Session issuance, renewal, and bypass prevention

On wallet login, require invitation + approved-wallet proof + fresh balance/price + active grant before issuing the existing opaque session. Cap sessions at 15 minutes and grant expiry. Tag session authentication mode and wallet binding server-side. Recheck eligibility at every renewal; obtain fresh wallet proof through a session-authenticated renewal challenge. Missing/stale price or failed balance check denies issuance/renewal. A failed renewal must not extend the old session.

Perform external RPC/price IO before taking the grant execution gate, then recheck snapshot age, grant revision, owner approval, revocation, and storage/audit health under the gate immediately before issuance. Reserve proof against concurrent use; revocation must not wait on a hung RPC. Never persist usable credentials.

Crucially, block the existing invitation-only exchange and generic renewal paths from bypassing wallet requirements for wallet-mode grants. Preserve ordinary invitation-only grants as an explicit separate owner choice. Balance drops/transfers or pricing outages do not retroactively cancel an existing session; it lasts at most the remaining 15 minutes. Owner revocation remains immediate. Existing replay and final-dispatch guards remain authoritative.

### 5. Usable owner and guest screens

Owner: create grant → enter/approve full wallet → select reviewed light/actions/expiry → issue invitation → inspect/revoke. Guest: paste invitation → choose Phantom/Solflare/Trust → verify displayed site and sign → view eligibility and permitted controls. Explain insufficient balance, stale price, unsupported wallet, and expired invitation without leaking other users' data. Show price observation age so an API fetch cannot appear to refresh an old valuation.

A wallet-only identity does not require a HA account. Do not return the homeowner's HA credential. No transaction or token approval should ever appear in this login flow.

### 6. Security and release gates

Add tests for schema migration; owner/admin separation; wrong mint, program, decimals or network; Token-2022 and multiple accounts; exact $2 boundary; malformed/nonfinite/stale/future prices; RPC timeout/429; stale observation with fresh HTTP response; wrong wallet/origin/installation; signature replay/races; denied alternate exchange/renewal paths; revoked/expired grant during RPC/audit; secret redaction; and all three wallet adapters.

Use reproducible synthetic RPC/price data for the automated suite, plus a recorded read-only live mint/price smoke test. Manually test supported desktop/mobile wallet versions on HTTPS and actual HA transport before claiming compatibility. Keep guest and wallet access default-off; no automatic production enablement. A live test must demonstrate an approved wallet succeeds with a fresh qualifying price while an unapproved wallet holding more coins is denied. Current stale-price evidence is a required denial fixture, not a reason to relax validation.

## Sources and reproducibility

- [Solana getAccountInfo](https://solana.com/docs/rpc/http/getaccountinfo): live POST to mainnet RPC with `encoding: jsonParsed`, `commitment: finalized`, and the exact mint above.
- [Solana getTokenAccountsByOwner](https://solana.com/docs/rpc/http/gettokenaccountsbyowner).
- [Jupiter Price API](https://developers.jup.ag/docs/price): live GET `https://api.jup.ag/price/v3?ids=ERAMuCbBAfHhxNCEb2ZJgf9rLJ4KBbvY1bD9dzHgpump`; source-slot time independently checked with RPC `getBlockTime`.
- [DEX Screener market](https://dexscreener.com/solana/72ofdxz4xlmdafvo35paolx2fsrrmtneqq2xzhjqdodc): read-only token-pairs API corroboration, not the proposed authorization price source.
- [Phantom message signing](https://docs.phantom.com/solana/signing-a-message) and [provider requirements](https://docs.phantom.com/solana/detecting-the-provider).
- [Solflare message signing](https://docs.solflare.com/solflare/technical/deeplinks/provider-methods/signmessage).
- [Trust Wallet official Connect SDK](https://github.com/trustwallet/trust-connect-sdk): Solana message signing and mobile WalletConnect support.
- [Solana message authentication](https://solana.com/docs/frontend/messages-and-auth): nonce handling, signature verification, supported message formats.
