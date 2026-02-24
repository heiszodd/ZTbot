import asyncio
import base64
import json
import logging

import httpx
from base58 import b58decode
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction

log = logging.getLogger(__name__)
JUPITER_SWAP_URL = "https://quote-api.jup.ag/v6/swap"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


async def get_sol_keypair() -> Keypair:
    from security.key_manager import get_private_key

    try:
        raw = get_private_key("sol_hot_wallet")
    except ValueError as e:
        raise RuntimeError(f"Solana hot wallet not configured: {e}\nUse /addkey to store sol_hot_wallet")

    try:
        secret = bytes(json.loads(raw)) if raw.startswith("[") else b58decode(raw)
        return Keypair.from_bytes(secret)
    except Exception as e:
        raise RuntimeError(f"Invalid Solana private key format: {type(e).__name__}: {e}")


async def execute_jupiter_swap(plan: dict) -> dict:
    raw_quote = plan.get("raw_quote")
    if not raw_quote:
        return {"success": False, "error": "No Jupiter quote in plan. Re-generate trade plan."}
    try:
        keypair = await asyncio.wait_for(get_sol_keypair(), timeout=5)
    except Exception as e:
        return {"success": False, "error": str(e)}

    import db
    from config import HELIUS_API_KEY
    mev_protection = db.get_user_settings().get("mev_protection", True)
    swap_payload = {
        "quoteResponse": raw_quote,
        "userPublicKey": str(keypair.pubkey()),
        "wrapAndUnwrapSol": True,
        "dynamicComputeUnitLimit": True,
        "prioritizationFeeLamports": "auto",
    }
    if mev_protection and HELIUS_API_KEY:
        swap_payload["jitoTipLamports"] = 1000000

    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(JUPITER_SWAP_URL, json=swap_payload, headers={"Content-Type": "application/json"})
            if r.status_code == 400:
                return {"success": False, "error": f"Jupiter swap: {r.json().get('error','')}"}
            r.raise_for_status()
            swap_data = r.json()
    except Exception as e:
        return {"success": False, "error": f"Jupiter API error: {e}"}

    try:
        tx_bytes = base64.b64decode(swap_data["swapTransaction"])
        transaction = VersionedTransaction.from_bytes(tx_bytes)
        transaction.sign([keypair])
        signed_bytes = bytes(transaction)
    except Exception as e:
        return {"success": False, "error": f"Transaction signing failed: {type(e).__name__}: {e}"}

    submitted = await _submit_transaction(signed_bytes, mev_protection)
    if not submitted.get("success"):
        return submitted
    signature = submitted["signature"]
    confirmed = await _confirm_transaction(signature)
    if confirmed.get("success") is False:
        log.warning("Tx confirmation uncertain: %s", signature)
    return {"success": True, "tx_id": signature, "tx_url": f"https://solscan.io/tx/{signature}", "tokens_out": plan.get("tokens_out", 0), "confirmed": confirmed.get("success", False)}


async def _submit_transaction(signed_bytes: bytes, mev_protection: bool = True) -> dict:
    from config import HELIUS_API_KEY, SOLANA_RPC_URL
    import base64 as b64

    tx_b64 = b64.b64encode(signed_bytes).decode()
    if mev_protection and HELIUS_API_KEY:
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.post("https://mainnet.block-engine.jito.wtf/api/v1/transactions", json={"jsonrpc": "2.0", "id": 1, "method": "sendTransaction", "params": [tx_b64, {"encoding": "base64", "skipPreflight": True}]})
                data = r.json()
                if "result" in data:
                    return {"success": True, "signature": data["result"], "via": "jito"}
        except Exception:
            pass

    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(SOLANA_RPC_URL, json={"jsonrpc": "2.0", "id": 1, "method": "sendTransaction", "params": [tx_b64, {"encoding": "base64", "skipPreflight": False, "preflightCommitment": "confirmed"}]})
            data = r.json()
            if "error" in data:
                return {"success": False, "error": f"RPC error: {data['error'].get('message','?')}"}
            return {"success": True, "signature": data["result"], "via": "rpc"}
    except Exception as e:
        return {"success": False, "error": f"Submit failed: {e}"}


async def _confirm_transaction(signature: str, max_retries: int = 20, interval: float = 2.0) -> dict:
    from config import SOLANA_RPC_URL
    for _ in range(max_retries):
        await asyncio.sleep(interval)
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.post(SOLANA_RPC_URL, json={"jsonrpc": "2.0", "id": 1, "method": "getSignatureStatuses", "params": [[signature], {"searchTransactionHistory": True}]})
                status = (r.json().get("result", {}).get("value", [None]) or [None])[0]
                if status is None:
                    continue
                err = status.get("err", "PENDING")
                if err is None:
                    return {"success": True, "confirmations": status.get("confirmations", 1), "status": status.get("confirmationStatus", "confirmed")}
                if err != "PENDING":
                    return {"success": False, "error": f"Tx failed: {err}"}
        except Exception:
            continue
    return {"success": None, "error": "Confirmation timeout — check Solscan for tx status"}


async def execute_sol_sell(plan: dict) -> dict:
    return await execute_jupiter_swap(plan)
