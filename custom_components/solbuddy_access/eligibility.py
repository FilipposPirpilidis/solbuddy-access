"""Read-only finalized Token-2022 holdings and fresh Jupiter USD valuation."""

import asyncio
import json
import math
import re
from dataclasses import dataclass
from decimal import Decimal
from time import monotonic
from urllib.parse import urlsplit

from aiohttp import ClientSession

from .auth import AuthError
from .wallet_identity import MAINNET_GENESIS, MINT, TOKEN_PROGRAM, public_key

PRICE_URL = "https://api.jup.ag/price/v3"
MAX_PRICE_AGE = 300
MAX_BALANCE_AGE = 60


class ObservationAgeError(AuthError):
    """Only observation ages/statuses may cross the authenticated error boundary."""

    def __init__(self, observations: dict):
        super().__init__(503, "eligibility_stale")
        self.observations = observations

    def response_data(self) -> dict:
        return super().response_data() | {"observations": self.observations}


@dataclass(frozen=True, repr=False)
class Evidence:
    wallet: str
    price_time: int
    balance_time: int
    deadline: float

    def check(self, wallet: str, now: float) -> None:
        if self.wallet != wallet or not math.isfinite(now):
            raise AuthError(503, "eligibility_unavailable")
        observations = {}
        for name, timestamp, limit in (
            ("price", self.price_time, MAX_PRICE_AGE),
            ("balance", self.balance_time, MAX_BALANCE_AGE),
        ):
            age = now - timestamp
            if not math.isfinite(age):
                raise AuthError(503, "eligibility_unavailable")
            observations[name] = {
                "status": "future" if age < 0 else "stale" if age > limit else "fresh",
                # Round away from zero for display only. Decisions use exact age.
                "age_seconds": math.ceil(age) if age >= 0 else math.floor(age),
                "max_age_seconds": limit,
            }
        if any(value["status"] != "fresh" for value in observations.values()):
            raise ObservationAgeError(observations)
        if monotonic() >= self.deadline:
            raise AuthError(503, "eligibility_expired")


def integer(value, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError("Invalid integer")
    return value


def parsed_account(value, expected_type):
    if value["owner"] != TOKEN_PROGRAM or value["executable"] is not False:
        raise ValueError("Wrong token program")
    data = value["data"]
    if data["program"] != "spl-token-2022" or data["parsed"]["type"] != expected_type:
        raise ValueError("Wrong token data")
    return data["parsed"]["info"]


def validate_mint(value):
    info = parsed_account(value, "mint")
    if (
        integer(info["decimals"]) != 6
        or info["isInitialized"] is not True
        or info["mintAuthority"] is not None
        or info["freezeAuthority"] is not None
    ):
        raise ValueError("Unexpected mint")
    for ext in info.get("extensions", []):
        if ext["extension"] not in {"metadataPointer", "tokenMetadata"}:
            raise ValueError("Unsupported mint extension")


def balance(accounts, wallet):
    if type(accounts) is not list or len(accounts) > 100:
        raise ValueError("Invalid accounts")
    seen, total = set(), 0
    for account in accounts:
        key = account["pubkey"]
        public_key(key)
        if key in seen:
            raise ValueError("Duplicate account")
        seen.add(key)
        info = parsed_account(account["account"], "account")
        if (
            info["mint"] != MINT
            or info["owner"] != wallet
            or info["state"] != "initialized"
            or info["isNative"] is not False
        ):
            raise ValueError("Unexpected token account")
        if any(
            ext["extension"] != "immutableOwner" for ext in info.get("extensions", [])
        ):
            raise ValueError("Unsupported account extension")
        amount = info["tokenAmount"]
        if (
            integer(amount["decimals"]) != 6
            or type(amount["amount"]) is not str
            or not re.fullmatch(r"[0-9]{1,20}", amount["amount"])
        ):
            raise ValueError("Invalid amount")
        raw = int(amount["amount"])
        if raw > 2**64 - 1:
            raise ValueError("Invalid amount")
        total += raw
    return total


class Eligibility:
    def __init__(
        self,
        session: ClientSession,
        rpc_url="https://api.mainnet-beta.solana.com",
        api_key="",
    ):
        parts = urlsplit(rpc_url)
        if (
            parts.scheme != "https"
            or not parts.hostname
            or parts.username
            or parts.password
            or parts.fragment
        ):
            raise ValueError("HTTPS RPC required")
        self.session, self.rpc_url, self.api_key = session, rpc_url, api_key
        self._slots = asyncio.Semaphore(4)

    async def _json(self, method, url, **kwargs):
        # No redirects, raw exception logging, or unbounded decompressed responses.
        async with self.session.request(
            method, url, allow_redirects=False, **kwargs
        ) as response:
            if response.status != 200:
                raise AuthError(503, "eligibility_unavailable")
            raw = bytearray()
            async for chunk in response.content.iter_chunked(8192):
                raw.extend(chunk)
                if len(raw) > 262144:
                    raise ValueError("Response too large")
            return json.loads(
                raw,
                parse_float=Decimal,
                parse_constant=lambda _: (_ for _ in ()).throw(
                    ValueError("Invalid number")
                ),
            )

    async def _rpc(self, method, params=None):
        result = await self._json(
            "POST",
            self.rpc_url,
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or []},
        )
        if result.get("jsonrpc") != "2.0" or result.get("id") != 1 or "error" in result:
            raise ValueError("Invalid RPC response")
        return result["result"]

    async def verify(self, wallet, now):
        public_key(wallet)
        try:
            async with asyncio.timeout(12), self._slots:
                if await self._rpc("getGenesisHash") != MAINNET_GENESIS:
                    raise ValueError("Wrong network")
                mint = await self._rpc(
                    "getAccountInfo",
                    [MINT, {"encoding": "jsonParsed", "commitment": "finalized"}],
                )
                validate_mint(mint["value"])
                mint_slot = integer(mint["context"]["slot"], 1)
                accounts = await self._rpc(
                    "getTokenAccountsByOwner",
                    [
                        wallet,
                        {"mint": MINT},
                        {
                            "encoding": "jsonParsed",
                            "commitment": "finalized",
                            "minContextSlot": mint_slot,
                        },
                    ],
                )
                slot = integer(accounts["context"]["slot"], mint_slot)
                raw = balance(accounts["value"], wallet)
                prices = await self._json(
                    "GET",
                    PRICE_URL,
                    params={"ids": MINT},
                    headers={"x-api-key": self.api_key} if self.api_key else {},
                )
                price = prices[MINT]
                if integer(price["decimals"]) != 6:
                    raise ValueError("Wrong price decimals")
                usd = price["usdPrice"]
                if (
                    type(usd) not in (Decimal, int)
                    or not Decimal(usd).is_finite()
                    or usd <= 0
                ):
                    raise ValueError("Invalid price")
                price_slot = integer(price["blockId"], 1)
                price_time = integer(await self._rpc("getBlockTime", [price_slot]), 1)
                balance_time = integer(await self._rpc("getBlockTime", [slot]), 1)
                evidence = Evidence(wallet, price_time, balance_time, monotonic() + 30)
                evidence.check(wallet, now().timestamp())
                if Decimal(raw) * Decimal(usd) / Decimal(1_000_000) < Decimal("2.00"):
                    raise AuthError(403, "insufficient_sbud")
                return evidence
        except AuthError:
            raise
        except Exception:
            raise AuthError(503, "eligibility_unavailable") from None


def load_provider_config(config_dir):
    """Optional owner file with !secret support; never send provider keys to UI."""
    from pathlib import Path

    from homeassistant.util.yaml import Secrets, load_yaml_dict

    path = Path(config_dir) / "solbuddy_access_wallet.yaml"
    try:
        data = (
            load_yaml_dict(path, secrets=Secrets(Path(config_dir)))
            if path.exists()
            else {}
        )
        if set(data) - {"rpc_url", "jupiter_api_key"}:
            raise ValueError("Invalid provider configuration")
        rpc, key = (
            data.get("rpc_url", "https://api.mainnet-beta.solana.com"),
            data.get("jupiter_api_key", ""),
        )
        if (
            not isinstance(rpc, str)
            or len(rpc) > 2048
            or not isinstance(key, str)
            or len(key) > 1024
        ):
            raise ValueError("Invalid provider configuration")
        return str(rpc), str(key)
    except Exception:
        raise ValueError("Wallet provider configuration unavailable") from None
