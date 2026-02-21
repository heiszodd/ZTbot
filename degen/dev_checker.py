from __future__ import annotations

KNOWN_RUG_WALLETS: set[str] = set()
_wallet_age_cache: dict[str, int] = {}


def load_known_rug_wallets(wallets: list[str]) -> None:
    KNOWN_RUG_WALLETS.update([w for w in wallets if w])


def check_dev_network(dev_wallet: str, chain: str) -> dict:
    funding_wallet = ""
    sibling_rugger_count = 0
    network_risk = 0
    conns = []
    if dev_wallet in KNOWN_RUG_WALLETS:
        network_risk += 30
        conns.append({"type": "dev_funded_known_rugger", "wallet": dev_wallet})
    if funding_wallet in KNOWN_RUG_WALLETS:
        network_risk += 40
    if sibling_rugger_count > 0:
        network_risk += sibling_rugger_count * 20
    if network_risk == 0:
        network_risk = -10
        label = "✅ No network connections to known rugs"
        rep = "clean"
    else:
        label = f"💀 Connected to {sibling_rugger_count} other ruggers" if sibling_rugger_count else "💀 Dev network risk found"
        rep = "risky"
    return {"funding_wallet": funding_wallet, "funding_wallet_reputation": rep, "sibling_rugger_count": sibling_rugger_count, "network_risk_added": network_risk, "network_label": label, "connections": conns}


def cache_wallet_creation_date(wallet: str, created_ts: int) -> int:
    if wallet in _wallet_age_cache:
        return _wallet_age_cache[wallet]
    _wallet_age_cache[wallet] = created_ts
    return created_ts
