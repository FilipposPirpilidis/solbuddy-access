"""Pinned wallet policy and canonical public-key codec (no key custody)."""

MINT = "ERAMuCbBAfHhxNCEb2ZJgf9rLJ4KBbvY1bD9dzHgpump"
TOKEN_PROGRAM = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
MAINNET_GENESIS = "5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d"
WALLET_POLICY = "solana-mainnet-sbud-usd2-v1"
ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def encode_key(raw: bytes) -> str:
    number, result = int.from_bytes(raw, "big"), ""
    while number:
        number, remainder = divmod(number, 58)
        result = ALPHABET[remainder] + result
    return "1" * (len(raw) - len(raw.lstrip(b"\0"))) + result


def public_key(value: object) -> bytes:
    if type(value) is not str or not 32 <= len(value) <= 44:
        raise ValueError("Invalid wallet address")
    number = 0
    for char in value:
        if char not in ALPHABET:
            raise ValueError("Invalid wallet address")
        number = number * 58 + ALPHABET.index(char)
    raw = b"\0" * (len(value) - len(value.lstrip("1"))) + number.to_bytes(
        (number.bit_length() + 7) // 8, "big"
    )
    if len(raw) != 32 or encode_key(raw) != value or raw == bytes(32):
        raise ValueError("Invalid wallet address")
    return raw
