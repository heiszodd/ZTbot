import json
import logging
import re
import hashlib
import hmac

log = logging.getLogger(__name__)


def detect_key_type(raw: str) -> str:
    raw = (raw or "").strip()
    words = raw.split()
    if len(words) in (12, 15, 18, 21, 24) and all(re.match(r"^[a-z]+$", w) for w in words):
        return "sol_seed"
    if re.match(r"^0x[a-fA-F0-9]{64}$", raw) or re.match(r"^[a-fA-F0-9]{64}$", raw):
        return "eth_privkey"
    if re.match(r"^[1-9A-HJ-NP-Za-km-z]{87,88}$", raw) or (raw.startswith("[") and raw.endswith("]")):
        return "sol_privkey"
    if re.match(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$", raw) or re.match(r"^0x[a-fA-F0-9]{40}$", raw):
        return "pubkey_only"
    return "unknown"


def _derive_solana_keypair(seed_bytes: bytes):
    from solders.keypair import Keypair

    def derive_child(parent_key: bytes, parent_chain: bytes, index: int):
        hardened = index + 0x80000000
        data = b"\x00" + parent_key + hardened.to_bytes(4, "big")
        d = hmac.new(parent_chain, data, hashlib.sha512).digest()
        return d[:32], d[32:]

    h = hmac.new(b"ed25519 seed", seed_bytes, hashlib.sha512).digest()
    key, chain = h[:32], h[32:]
    for index in [44, 501, 0, 0]:
        key, chain = derive_child(key, chain, index)
    return Keypair.from_seed(key)


def solana_keypair_from_seed(seed_phrase: str):
    from solders.keypair import Keypair

    phrase = seed_phrase.strip()
    try:
        from mnemonic import Mnemonic

        mnemo = Mnemonic("english")
        if not mnemo.check(phrase):
            raise ValueError("Invalid seed phrase — check words are correct BIP39 words")
        seed_bytes = mnemo.to_seed(phrase, passphrase="")
        return _derive_solana_keypair(seed_bytes)
    except ImportError:
        log.warning("mnemonic library missing, using fallback derivation")
        seed_bytes = hashlib.pbkdf2_hmac("sha512", phrase.encode("utf-8"), b"mnemonic", 2048)
        return Keypair.from_seed(seed_bytes[:32])


def solana_keypair_from_privkey(raw: str):
    from solders.keypair import Keypair

    raw = raw.strip()
    if raw.startswith("["):
        return Keypair.from_bytes(bytes(json.loads(raw)))
    from base58 import b58decode

    return Keypair.from_bytes(b58decode(raw))


def solana_keypair_from_any(raw: str):
    key_type = detect_key_type(raw)
    if key_type == "sol_seed":
        return solana_keypair_from_seed(raw), "seed_phrase"
    if key_type == "sol_privkey":
        return solana_keypair_from_privkey(raw), "private_key"
    if key_type == "pubkey_only":
        raise ValueError(
            "❌ This looks like a PUBLIC KEY or wallet ADDRESS, not a private key.\n\n"
            "I need your PRIVATE KEY to execute trades. Please provide:\n\n"
            "• Your 12 or 24 word seed phrase\n"
            "• OR your base58 private key (87-88 chars)\n\n"
            "In Phantom: Settings → Security → Show Private Key or Secret Recovery Phrase"
        )
    raise ValueError(
        "❌ Unrecognised key format.\n\n"
        "Accepted formats:\n• 12 or 24 word seed phrase\n• Base58 private key (87-88 chars)\n• JSON byte array [1,2,3...]"
    )


def eth_account_from_seed(seed_phrase: str):
    from eth_account import Account

    Account.enable_unaudited_hdwallet_features()
    try:
        return Account.from_mnemonic(seed_phrase.strip(), account_path="m/44'/60'/0'/0/0")
    except Exception as e:
        raise ValueError(f"Could not derive ETH account from seed phrase: {e}\nCheck all words are valid BIP39 words.")


def eth_account_from_privkey(raw: str):
    from eth_account import Account

    raw = raw.strip()
    if not raw.startswith("0x"):
        raw = "0x" + raw
    try:
        return Account.from_key(raw)
    except Exception as e:
        raise ValueError(f"Invalid Ethereum private key: {e}")


def eth_account_from_any(raw: str):
    key_type = detect_key_type(raw)
    if key_type == "sol_seed":
        return eth_account_from_seed(raw), "seed_phrase"
    if key_type == "eth_privkey":
        return eth_account_from_privkey(raw), "private_key"
    if key_type == "pubkey_only":
        raise ValueError(
            "❌ This looks like a PUBLIC ADDRESS, not a private key.\n\n"
            "I need your PRIVATE KEY to sign transactions. Please provide:\n\n"
            "• 12 or 24 word seed phrase\n• OR 64-char hex private key (with or without 0x)\n\n"
            "In MetaMask: Account Details → Export Private Key"
        )
    raise ValueError(
        "❌ Unrecognised Ethereum key format.\n\nAccepted formats:\n• 12 or 24 word seed phrase\n• Hex private key (64 chars) with/without 0x"
    )


def get_sol_address_from_any(raw: str) -> str:
    kp, _ = solana_keypair_from_any(raw)
    return str(kp.pubkey())


def get_eth_address_from_any(raw: str) -> str:
    acct, _ = eth_account_from_any(raw)
    return acct.address


def normalise_for_storage(raw: str, chain: str) -> str:
    raw = raw.strip()
    if chain == "solana":
        kp, _ = solana_keypair_from_any(raw)
        from base58 import b58encode

        return b58encode(bytes(kp)).decode()
    if chain in ("ethereum", "hyperliquid", "polymarket"):
        acct, _ = eth_account_from_any(raw)
        key_hex = acct.key.hex()
        return key_hex if key_hex.startswith("0x") else f"0x{key_hex}"
    raise ValueError(f"Unknown chain: {chain}")
