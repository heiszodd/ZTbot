from __future__ import annotations

TEMPLATES = {
    "safe_hunter": {
        "name": "🛡️ Safe Hunter",
        "description": "Low-risk tokens with locked LP, revoked authorities, and clean dev wallets",
        "rules": [
            {"id": "no_honeypot", "mandatory": True},
            {"id": "dev_not_serial_rugger", "mandatory": True},
            {"id": "mint_revoked"}, {"id": "freeze_revoked"}, {"id": "lp_locked_50"}, {"id": "rugcheck_safe"}, {"id": "top1_under_10"}, {"id": "contract_verified"},
        ],
    },
    "fresh_launch": {
        "name": "🚀 Fresh Launch Sniper",
        "description": "Tokens under 30 minutes old with buying pressure and meme narrative",
        "rules": [{"id": "no_honeypot", "mandatory": True}, {"id": "under_30min"}, {"id": "buyers_dominating"}, {"id": "volume_active"}, {"id": "meme_narrative"}, {"id": "has_telegram"}],
    },
    "clean_dev": {
        "name": "👨‍💻 Clean Dev Only",
        "description": "Strict dev reputation filter — zero rug history required",
        "rules": [{"id": "no_honeypot", "mandatory": True}, {"id": "dev_not_serial_rugger", "mandatory": True}, {"id": "dev_no_rugs", "mandatory": True}, {"id": "dev_wallet_age_7d"}, {"id": "dev_low_supply"}, {"id": "mint_revoked"}, {"id": "freeze_revoked"}],
    },
    "micro_cap": {
        "name": "💎 Micro Cap Gem",
        "description": "Under $50K market cap, 100+ holders, locked LP, active community",
        "rules": [{"id": "no_honeypot", "mandatory": True}, {"id": "micro_cap"}, {"id": "holder_count_100"}, {"id": "lp_locked"}, {"id": "moon_over_50"}, {"id": "buyers_dominating"}, {"id": "meme_narrative"}],
    },
    "moonshot": {
        "name": "🌕 Moonshot Hunter",
        "description": "High moon score, strong momentum, full socials — maximum upside focus",
        "rules": [{"id": "no_honeypot", "mandatory": True}, {"id": "moon_over_70"}, {"id": "strong_buyers"}, {"id": "volume_strong"}, {"id": "full_socials"}, {"id": "positive_1h"}, {"id": "small_cap"}],
    },
    "dev_checker": {
        "name": "👨‍💻 Dev Checker",
        "description": "Template",
        "rules": [{"id": "no_honeypot", "mandatory": True}, {"id": "dev_not_serial_rugger", "mandatory": True}, {"id": "dev_no_rugs", "mandatory": True}, {"id": "dev_wallet_age_7d"}, {"id": "dev_low_supply"}, {"id": "mint_revoked"}, {"id": "freeze_revoked"}],
    },
    "gem_hunter": {
        "name": "💎 Gem Hunter",
        "description": "Template",
        "rules": [{"id": "no_honeypot", "mandatory": True}, {"id": "micro_cap"}, {"id": "holder_count_100"}, {"id": "lp_locked"}, {"id": "moon_over_50"}, {"id": "buyers_dominating"}, {"id": "meme_narrative"}],
    },
    "narrative_play": {
        "name": "🔥 Narrative Play",
        "description": "Template",
        "rules": [{"id": "no_honeypot", "mandatory": True}, {"id": "meme_narrative"}, {"id": "has_twitter"}, {"id": "has_telegram"}, {"id": "high_engagement"}, {"id": "positive_1h"}, {"id": "small_cap"}],
    },
}
