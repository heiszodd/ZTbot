"""
security/key_manager.py
Encrypted key storage and retrieval.
All functions return safe defaults on error.
"""

import logging

log = logging.getLogger(__name__)

_cache: dict = {}


def _clear_key_cache() -> None:
    _cache.clear()


def key_exists(key_name: str) -> bool:
    """Check if a key is stored. NEVER raises."""
    try:
        import db

        result = db.get_encrypted_key(key_name)
        return result is not None
    except Exception:
        return False


def store_private_key(
    key_name: str,
    raw_input: str,
    label: str = "",
    chain: str = "solana",
) -> dict:
    """Validate, normalise, encrypt and store key."""
    raw = (raw_input or "").strip()
    if not raw:
        raise ValueError("No key provided. Please send your seed phrase or private key.")

    words = raw.split()
    is_seed = len(words) in (12, 15, 18, 21, 24) and all(w.isalpha() for w in words)

    is_eth_address = raw.startswith("0x") and len(raw) == 42
    is_sol_pubkey = (not is_seed and not raw.startswith("0x") and 32 <= len(raw) <= 44 and len(words) == 1)
    if is_eth_address or is_sol_pubkey:
        raise ValueError(
            "❌ That looks like a public address,\nnot a private key.\n\n"
            "Please provide:\n"
            "• Your 12 or 24 word seed phrase\n"
            "• OR your private key"
        )

    address = ""
    normalised = raw
    if chain == "solana":
        address, normalised = _process_solana_key(raw, is_seed)
    elif chain in ("hyperliquid", "polymarket", "ethereum"):
        address, normalised = _process_eth_key(raw, is_seed)
    else:
        address = key_name
        normalised = raw

    from security.encryption import encrypt_secret

    try:
        encrypted = encrypt_secret(normalised)
    except Exception as e:
        raise ValueError(f"Encryption failed: {e}\nCheck ENCRYPTION_KEY environment variable.")

    import db

    ok = db.save_encrypted_key(
        {"key_name": key_name, "encrypted": encrypted, "label": label or key_name}
    )
    if not ok:
        raise ValueError("Failed to save key to database.\nCheck Supabase connection.")

    _cache.pop(key_name, None)
    log.info("Key stored: %s chain=%s addr=%s...", key_name, chain, address[:10] if address else "?")
    return {"address": address, "format": "seed_phrase" if is_seed else "private_key"}


def get_private_key(key_name: str) -> str:
    if key_name in _cache:
        return _cache[key_name]

    import db

    record = db.get_encrypted_key(key_name)
    if not record:
        raise ValueError(f"Key '{key_name}' not found.\nPlease connect your wallet first.")

    from security.encryption import decrypt_secret

    try:
        decrypted = decrypt_secret(record["encrypted"])
    except Exception as e:
        raise ValueError(f"Could not decrypt key '{key_name}': {e}")

    _cache[key_name] = decrypted
    return decrypted


def delete_key(key_name: str) -> bool:
    try:
        import db

        db.delete_encrypted_key(key_name)
        _cache.pop(key_name, None)
        return True
    except Exception:
        return False


def delete_private_key(key_name: str) -> None:
    if not delete_key(key_name):
        raise RuntimeError("Failed to delete key")


def list_stored_keys() -> list:
    try:
        import db

        records = db.list_encrypted_keys()
        return [
            {"key_name": r.get("key_name"), "label": r.get("label"), "stored_at": r.get("stored_at")}
            for r in records
        ]
    except Exception:
        return []


def _process_solana_key(raw: str, is_seed: bool) -> tuple[str, str]:
    try:
        from solders.keypair import Keypair

        if is_seed:
            try:
                from mnemonic import Mnemonic

                mnemo = Mnemonic("english")
                seed_bytes = mnemo.to_seed(raw, passphrase="")
                kp = _derive_sol_keypair(seed_bytes)
            except ImportError:
                import hashlib

                seed_bytes = hashlib.pbkdf2_hmac("sha512", raw.encode(), b"mnemonic", 2048)
                kp = Keypair.from_seed(seed_bytes[:32])
        else:
            try:
                from base58 import b58decode

                secret = b58decode(raw)
                kp = Keypair.from_bytes(secret)
            except Exception:
                import json

                byte_list = json.loads(raw)
                kp = Keypair.from_bytes(bytes(byte_list))

        from base58 import b58encode

        address = str(kp.pubkey())
        normalised = b58encode(bytes(kp)).decode()
        return address, normalised
    except Exception as e:
        raise ValueError(f"Could not load Solana key: {e}\n\nCheck your seed phrase or private key and try again.")


def _derive_sol_keypair(seed_bytes: bytes):
    import hmac
    import hashlib
    from solders.keypair import Keypair

    def child(key, chain, index):
        h = index + 0x80000000
        data = b"\x00" + key + h.to_bytes(4, "big")
        d = hmac.new(chain, data, hashlib.sha512).digest()
        return d[:32], d[32:]

    h = hmac.new(b"ed25519 seed", seed_bytes, hashlib.sha512).digest()
    key, chain = h[:32], h[32:]
    for i in [44, 501, 0, 0]:
        key, chain = child(key, chain, i)
    return Keypair.from_seed(key)


def _process_eth_key(raw: str, is_seed: bool) -> tuple[str, str]:
    try:
        from eth_account import Account

        if is_seed:
            Account.enable_unaudited_hdwallet_features()
            acct = Account.from_mnemonic(raw, account_path="m/44'/60'/0'/0/0")
        else:
            key = raw if raw.startswith("0x") else "0x" + raw
            acct = Account.from_key(key)

        return acct.address, acct.key.hex()
    except Exception as e:
        raise ValueError(f"Could not load ETH key: {e}\n\nCheck your seed phrase or private key and try again.")
