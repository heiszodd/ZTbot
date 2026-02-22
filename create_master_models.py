import json

import psycopg2

import db
from config import DB_URL


NAME_TO_TAG = {
    "htf trend bullish": "htf_bullish",
    "htf trend bearish": "htf_bearish",
    "ltf bullish structure": "ltf_bullish_structure",
    "ltf bearish structure": "ltf_bearish_structure",
    "htf ltf aligned bullish": "htf_ltf_aligned_bull",
    "htf ltf aligned bearish": "htf_ltf_aligned_bear",
    "htf/ltf aligned bull": "htf_ltf_aligned_bull",
    "htf/ltf aligned bear": "htf_ltf_aligned_bear",
    "bullish ob present": "bullish_ob_present",
    "bearish ob present": "bearish_ob_present",
    "bullish order block": "bullish_ob_present",
    "bearish order block": "bearish_ob_present",
    "ob respected": "ob_respected",
    "order block respected": "ob_respected",
    "breaker block": "breaker_block",
    "ob on htf": "ob_on_htf",
    "htf order block": "ob_on_htf",
    "bullish fvg": "bullish_fvg",
    "bearish fvg": "bearish_fvg",
    "bullish fair value gap": "bullish_fvg",
    "bearish fair value gap": "bearish_fvg",
    "fvg within ob": "fvg_within_ob",
    "nested fvg": "nested_fvg",
    "liquidity swept bullish": "liquidity_swept_bull",
    "liquidity swept bearish": "liquidity_swept_bear",
    "liq sweep bull": "liquidity_swept_bull",
    "liq sweep bear": "liquidity_swept_bear",
    "asian range swept": "asian_range_swept",
    "stop hunt": "stop_hunt",
    "mss bullish": "mss_bullish",
    "mss bearish": "mss_bearish",
    "market structure shift bull": "mss_bullish",
    "market structure shift bear": "mss_bearish",
    "bos bullish": "bos_bullish",
    "bos bearish": "bos_bearish",
    "break of structure bull": "bos_bullish",
    "break of structure bear": "bos_bearish",
    "choch bullish": "choch_bullish",
    "choch bearish": "choch_bearish",
    "change of character bull": "choch_bullish",
    "change of character bear": "choch_bearish",
    "london session": "session_london",
    "ny session": "session_ny",
    "new york session": "session_ny",
    "session overlap": "session_overlap",
    "london open sweep": "london_open_sweep",
    "ny open reversal": "ny_open_reversal",
    "new york open reversal": "ny_open_reversal",
    "premium zone": "premium_zone",
    "discount zone": "discount_zone",
    "equilibrium": "equilibrium",
    "near htf level": "near_htf_level",
    "htf key level": "near_htf_level",
    "bullish engulfing": "bullish_engulfing",
    "bearish engulfing": "bearish_engulfing",
    "pin bar bullish": "pin_bar_bull",
    "pin bar bearish": "pin_bar_bear",
    "bullish pin bar": "pin_bar_bull",
    "bearish pin bar": "pin_bar_bear",
    "doji rejection": "doji_rejection",
    "volume spike": "volume_spike",
    "volume declining pullback": "volume_declining_pullback",
    "volume expanding breakout": "volume_expanding_breakout",
    "declining volume pullback": "volume_declining_pullback",
    "ote zone": "ote_zone",
    "optimal trade entry": "ote_zone",
    "power of three": "power_of_three",
    "judas swing": "judas_swing",
    "silver bullet window": "silver_bullet_window",
    "silver bullet": "silver_bullet_window",
    "midnight open": "midnight_open",
    "three confluences": "three_confluences",
    "3 confluences": "three_confluences",
    "news clear": "news_clear",
    "no major news": "news_clear",
    "higher high confirmation": "higher_high_confirmation",
    "lower low confirmation": "lower_low_confirmation",
    "higher high": "higher_high_confirmation",
    "lower low": "lower_low_confirmation",
}


def name_to_tag(name: str) -> str:
    if not name:
        return ""
    key = str(name).lower().strip()
    if key in NAME_TO_TAG:
        return NAME_TO_TAG[key]
    for prefix in ("rule: ", "rule ", "check "):
        if key.startswith(prefix):
            stripped = key[len(prefix):]
            if stripped in NAME_TO_TAG:
                return NAME_TO_TAG[stripped]
    best_tag = ""
    best_score = 0
    key_words = set(key.replace("-", " ").replace("_", " ").split())
    for label, tag in NAME_TO_TAG.items():
        label_words = set(label.split())
        overlap = len(key_words & label_words)
        if overlap > best_score:
            best_score = overlap
            best_tag = tag
    return best_tag if best_score >= 2 else ""


def make_rule(model_id, index, name, weight, mandatory=False, phase=1):
    tag = name_to_tag(name)
    if not tag:
        print(f"WARNING: No tag found for rule name='{name}' in model {model_id}")
    return {
        "id": f"{model_id}_rule_{index}",
        "name": name,
        "tag": tag,
        "weight": float(weight),
        "mandatory": bool(mandatory),
        "phase": phase,
        "description": name,
    }


def model(mid, name, pair, tf, session, bias, desc, rulespec, rr_target=2.0):
    rules = [make_rule(mid, i + 1, *row) for i, row in enumerate(rulespec)]
    total = sum(x["weight"] for x in rules)
    a, b, c = total * 0.8, total * 0.65, total * 0.5
    return {
        "id": mid, "name": name, "pair": "ALL", "timeframe": tf, "session": session, "bias": "Both",
        "status": "inactive", "rules": rules,
        "tier_a_threshold": a, "tier_b_threshold": b, "tier_c_threshold": c, "min_score": c,
        "description": desc, "tier_a": a, "tier_b": b, "tier_c": c, "rr_target": float(rr_target),
    }


MODELS = [
# Category 1
model("MM_TC_01","MASTER MODEL — Bullish Trend Continuation (BTC 4H)","BTCUSDT","4h","Any","Bullish","Catches pullbacks in a strong uptrend using OB, FVG, and HTF alignment for high-probability long entries.",[("HTF 1D trend is bullish",3.0,True),("4H structure is higher highs and higher lows",3.0,True),("Price has pulled back to a 4H bullish order block",2.5,False),("Fair value gap present within the OB zone",2.0,False),("RSI below 50 on 4H showing pullback momentum",1.5,False),("London or NY session open",1.0,False),("Volume declining on pullback confirming weak sellers",1.5,False)]),
model("MM_TC_02","MASTER MODEL — Bearish Trend Continuation (BTC 4H)","BTCUSDT","4h","Any","Bearish","Catches dead cat bounces in downtrends using bearish OBs, FVGs, and HTF confirmation for short entries.",[("HTF 1D trend is bearish",3.0,True),("4H structure is lower highs and lower lows",3.0,True),("Price has bounced into a 4H bearish order block",2.5,False),("Fair value gap filled within the OB zone",2.0,False),("RSI above 50 on 4H showing bounce exhaustion",1.5,False),("Bearish engulfing candle at OB",2.0,False),("Volume declining on bounce",1.5,False)]),
model("MM_TC_03","MASTER MODEL — ETH Bullish Trend Continuation (1H)","ETHUSDT","1h","London","Bullish","ETH 1H pullback entries during London session with BTC correlation confirmation.",[("BTC 4H bias is bullish",2.5,True),("ETH 1H structure is bullish",2.5,True),("ETH pulling back to 1H demand zone",2.0,False),("London session active",1.5,True),("1H FVG present at entry zone",2.0,False),("ETH/BTC ratio stable or rising",1.5,False),("Liquidity sweep of recent lows before entry",2.0,False)]),
model("MM_TC_04","MASTER MODEL — SOL Momentum Continuation (15M)","SOLUSDT","15m","NY","Bullish","SOL short-term momentum plays during NY session using microstructure and order flow.",[("SOL 1H trend is bullish",2.5,True),("15M market structure shift to bullish",2.5,True),("15M bullish OB respected on retest",2.0,False),("NY session active",1.5,False),("Volume above 20-period average on breakout",2.0,False),("BTC not showing major bearish move",1.5,False),("15M FVG acting as support",1.5,False)]),
model("MM_TC_05","MASTER MODEL — Gold Bullish Trend (1H)","XAUUSD","1h","London","Bullish","Gold long entries using ICT concepts during London session with dollar weakness confirmation.",[("Gold 4H trend is bullish",3.0,True),("USD showing weakness on DXY",2.5,True),("1H bullish OB respected",2.5,False),("London session open sweep of Asian lows",2.0,False),("1H FVG below price acting as support",2.0,False),("Price in discount on 4H range",1.5,False)]),
model("MM_TC_06","MASTER MODEL — EUR/USD Bullish Trend (1H)","EURUSD","1h","London","Bullish","EUR/USD long entries during London session using structure and OB confluence.",[("4H EURUSD trend is bullish",3.0,True),("London session opening range established",2.0,True),("Price sweeps Asian session lows then reverses",2.5,False),("1H bullish OB in play",2.0,False),("1H FVG present",1.5,False),("DXY showing bearish structure on 1H",2.0,False)]),
# Category 2
model("MM_REV_01","MASTER MODEL — Bullish Market Structure Shift (1H)","BTCUSDT","1h","Any","Bullish","Detects genuine trend reversals using MSS, liquidity sweeps, and OB formation for early long entries.",[("Prior 1H trend was bearish",2.0,False),("Liquidity sweep of key lows before reversal",3.0,True),("1H market structure shift to bullish confirmed",3.0,True),("First 1H bullish OB formed after MSS",2.5,False),("1H FVG left by the reversal impulse",2.0,False),("4H showing potential bottom formation",1.5,False),("Volume spike on the reversal candle",2.0,False)]),
model("MM_REV_02","MASTER MODEL — Bearish Market Structure Shift (1H)","BTCUSDT","1h","Any","Bearish","Detects genuine bearish reversals using MSS, liquidity sweeps, and OB formation for early short entries.",[("Prior 1H trend was bullish",2.0,False),("Liquidity sweep of key highs before reversal",3.0,True),("1H market structure shift to bearish confirmed",3.0,True),("First 1H bearish OB formed after MSS",2.5,False),("1H FVG left above price by reversal impulse",2.0,False),("4H showing potential top formation",1.5,False),("Volume spike on the reversal candle",2.0,False)]),
model("MM_REV_03","MASTER MODEL — Double Bottom Reversal (4H)","BTCUSDT","4h","Any","Bullish","Classic double bottom with liquidity engineering and OB confirmation for high R long entries.",[("Two equal lows formed on 4H",3.0,True),("Second low sweeps first low liquidity then recovers",3.0,True),("4H bullish OB above the double bottom neckline",2.5,False),("Bullish divergence on RSI or momentum",2.0,False),("Volume lower on second bottom than first",1.5,False),("4H FVG present above neckline",2.0,False),("HTF weekly or daily showing demand zone nearby",1.5,False)]),
model("MM_REV_04","MASTER MODEL — Double Top Reversal (4H)","BTCUSDT","4h","Any","Bearish","Double top with liquidity engineering and bearish OB confirmation for high R short entries.",[("Two equal highs formed on 4H",3.0,True),("Second high sweeps first high liquidity then reverses",3.0,True),("4H bearish OB below the double top neckline",2.5,False),("Bearish divergence on RSI or momentum",2.0,False),("Volume lower on second top than first",1.5,False),("4H FVG present below neckline",2.0,False),("HTF weekly or daily showing supply zone nearby",1.5,False)]),
model("MM_REV_05","MASTER MODEL — Gold Bearish Reversal at HTF Supply (4H)","XAUUSD","4h","NY","Bearish","Gold reversals at major supply zones during NY session with dollar strength confluence.",[("Gold at major 4H or weekly supply zone",3.0,True),("Liquidity sweep of recent highs before reversal",2.5,True),("4H bearish MSS confirmed",2.5,False),("DXY showing bullish structure on 1H",2.0,False),("Bearish engulfing or shooting star at supply",2.0,False),("4H FVG left below entry",1.5,False),("NY session active",1.0,False)]),
model("MM_REV_06","MASTER MODEL — EUR/USD Bearish Reversal (4H)","EURUSD","4h","London","Bearish","EUR/USD short entries at key supply zones during London session reversals.",[("EURUSD at 4H or weekly supply zone",3.0,True),("London session sweep of Asian highs before reversal",2.5,True),("4H bearish OB respected",2.5,False),("DXY breaking bullish structure",2.0,False),("1H bearish MSS confirmed",2.0,False),("4H bearish FVG below current price",1.5,False)]),
# Category 3
model("MM_LIQ_01","MASTER MODEL — Bullish Stop Hunt (15M)","BTCUSDT","15m","London","Bullish","Buy the stop hunt — price sweeps retail longs below key support then reverses aggressively.",[("Clear equal lows or prior swing low acting as support",3.0,True),("Price spikes below the lows then closes back above",3.5,True),("15M bullish OB formed immediately after the sweep",2.5,False),("15M MSS to bullish after sweep",2.5,False),("London session active for volume",1.5,False),("1H bias is bullish",2.0,False),("Rejection wick at least 2x the body size",1.5,False)]),
model("MM_LIQ_02","MASTER MODEL — Bearish Stop Hunt (15M)","BTCUSDT","15m","London","Bearish","Sell the stop hunt — price sweeps retail shorts above key resistance then reverses aggressively.",[("Clear equal highs or prior swing high acting as resistance",3.0,True),("Price spikes above the highs then closes back below",3.5,True),("15M bearish OB formed immediately after the sweep",2.5,False),("15M MSS to bearish after sweep",2.5,False),("London session active for volume",1.5,False),("1H bias is bearish",2.0,False),("Rejection wick at least 2x the body size",1.5,False)]),
model("MM_LIQ_03","MASTER MODEL — Asian Range Liquidity Grab Bullish (1H)","BTCUSDT","1h","London","Bullish","London session takes Asian session lows, then reverses bullish — classic session liquidity grab.",[("Asian session range clearly defined",2.5,True),("London open sweeps Asian session lows",3.0,True),("Price reverses and closes back inside Asian range",2.5,False),("1H bullish OB at the sweep level",2.0,False),("HTF 4H bias is bullish",2.0,False),("1H FVG left by the reversal impulse",1.5,False),("Sweep happens within first 2 hours of London open",1.5,False)]),
model("MM_LIQ_04","MASTER MODEL — Asian Range Liquidity Grab Bearish (1H)","BTCUSDT","1h","London","Bearish","London session takes Asian session highs then reverses bearish — fading the false break.",[("Asian session range clearly defined",2.5,True),("London open sweeps Asian session highs",3.0,True),("Price reverses and closes back inside Asian range",2.5,False),("1H bearish OB at the sweep level",2.0,False),("HTF 4H bias is bearish",2.0,False),("1H FVG left by the reversal impulse",1.5,False),("Sweep happens within first 2 hours of London open",1.5,False)]),
model("MM_LIQ_05","MASTER MODEL — NY Session Liquidity Sweep Bullish (1H)","XAUUSD","1h","NY","Bullish","NY open takes London session lows then drives higher — classic NY manipulation then distribution.",[("London session established a clear low",2.5,True),("NY open sweeps the London session low",3.0,True),("Bullish reversal candle after the sweep",2.5,False),("1H bullish OB respected at sweep zone",2.0,False),("HTF bias is bullish",2.0,False),("DXY showing weakness at NY open",1.5,False),("1H FVG left by NY reversal impulse",1.5,False)]),
model("MM_LIQ_06","MASTER MODEL — Equal Highs Hunt Bearish (4H)","ETHUSDT","4h","Any","Bearish","Targets the obvious equal highs that every retail trader has their stop above — then shorts the sweep.",[("Two or more equal highs clearly visible on 4H",3.0,True),("Price approaches equal highs from below",2.0,False),("Sweep of equal highs with wick rejection",3.0,True),("4H bearish OB forms below the sweep",2.5,False),("4H MSS to bearish after sweep",2.0,False),("Volume spike on the sweep candle",1.5,False),("1H bearish structure confirmed",1.5,False)]),
model("MM_LIQ_07","MASTER MODEL — Equal Lows Hunt Bullish (4H)","ETHUSDT","4h","Any","Bullish","Targets the obvious equal lows that every retail trader has their stop below — then longs the sweep.",[("Two or more equal lows clearly visible on 4H",3.0,True),("Price approaches equal lows from above",2.0,False),("Sweep of equal lows with wick rejection",3.0,True),("4H bullish OB forms above the sweep",2.5,False),("4H MSS to bullish after sweep",2.0,False),("Volume spike on the sweep candle",1.5,False),("1H bullish structure confirmed",1.5,False)]),
# Category 4
model("MM_OB_01","MASTER MODEL — 4H Bullish OB Retest (BTC)","BTCUSDT","4h","Any","Bullish","Pure order block retest model — waits for price to return to a fresh 4H bullish OB with confluence.",[("4H bullish OB identified and fresh (never retested)",3.0,True),("Price returns to the OB zone",3.0,True),("4H trend is bullish above the OB",2.5,False),("1H bullish reaction at the OB",2.5,False),("FVG within or just above the OB",2.0,False),("No previous wicks deep into the OB",1.5,False),("Volume drops as price enters OB",1.5,False)]),
model("MM_OB_02","MASTER MODEL — 4H Bearish OB Retest (BTC)","BTCUSDT","4h","Any","Bearish","Waits for price to return to a fresh 4H bearish OB in a downtrend for high-probability short entries.",[("4H bearish OB identified and fresh",3.0,True),("Price returns to the OB zone",3.0,True),("4H trend is bearish below the OB",2.5,False),("1H bearish reaction at the OB",2.5,False),("FVG within or just below the OB",2.0,False),("No previous wicks deep into the OB",1.5,False),("Volume drops as price enters OB",1.5,False)]),
model("MM_OB_03","MASTER MODEL — Weekly OB Bullish (BTC)","BTCUSDT","1d","Any","Bullish","Highest timeframe OB model — weekly bullish OBs for major swing long positions with maximum confluence.",[("Weekly bullish OB identified",4.0,True),("Daily trend is bullish",3.0,True),("Price pulls back to weekly OB zone",3.0,False),("Daily bullish OB within weekly OB zone",2.5,False),("Daily FVG present at entry zone",2.0,False),("Weekly RSI below 50 showing pullback",1.5,False),("Monthly bias is bullish",2.0,False)]),
model("MM_OB_04","MASTER MODEL — 1H Bullish OB Scalp (BTC)","BTCUSDT","1h","London","Bullish","Short-term 1H OB scalp model for London session with tight entries and quick TP targets.",[("4H bias is bullish",2.5,True),("1H bullish OB is fresh and unmitigated",3.0,True),("London session active",1.5,False),("15M bullish MSS confirms entry",2.5,False),("1H FVG above OB as target",2.0,False),("Volume declining on pullback to OB",1.5,False),("Previous 1H high as clear TP1 target",1.5,False)]),
model("MM_OB_05","MASTER MODEL — 1H Bearish OB Scalp (ETH)","ETHUSDT","1h","NY","Bearish","ETH 1H bearish OB scalps during NY session with BTC alignment for short-term shorts.",[("BTC 4H bias is bearish",2.5,True),("ETH 1H bearish OB fresh and unmitigated",3.0,True),("NY session active",1.5,False),("15M bearish MSS confirms entry",2.5,False),("1H FVG below OB as target",2.0,False),("ETH/BTC not showing relative strength",1.5,False),("Previous 1H low as clear TP1 target",1.5,False)]),
model("MM_OB_06","MASTER MODEL — Breaker Block Bullish (1H)","BTCUSDT","1h","Any","Bullish","A bearish OB that has been broken and retested as support — the breaker block entry.",[("Prior 1H bearish OB identified",2.5,True),("Price breaks above the bearish OB",3.0,True),("Price returns to retest the broken OB as support",3.0,True),("1H bullish reaction at the breaker",2.5,False),("4H bias is bullish",2.0,False),("FVG left by the breakout impulse",1.5,False),("Volume expands on the breakout candle",1.5,False)]),
model("MM_OB_07","MASTER MODEL — Breaker Block Bearish (1H)","BTCUSDT","1h","Any","Bearish","A bullish OB that has been broken and retested as resistance — the bearish breaker entry.",[("Prior 1H bullish OB identified",2.5,True),("Price breaks below the bullish OB",3.0,True),("Price returns to retest the broken OB as resistance",3.0,True),("1H bearish reaction at the breaker",2.5,False),("4H bias is bearish",2.0,False),("FVG left by the breakdown impulse",1.5,False),("Volume expands on the breakdown candle",1.5,False)]),
# Category 5
model("MM_FVG_01","MASTER MODEL — 1H Bullish FVG Fill Long (BTC)","BTCUSDT","1h","Any","Bullish","Price fills a bullish FVG from below then continues — entering as price taps into the imbalance.",[("1H bullish FVG identified and open",3.0,True),("Price approaches FVG from above (pullback)",2.5,True),("4H trend is bullish providing HTF context",2.5,False),("OB present within or near the FVG",2.0,False),("1H bullish candle reaction at FVG",2.0,False),("FVG is within a premium/discount range",1.5,False),("Less than 3 previous tests of this FVG",1.5,False)]),
model("MM_FVG_02","MASTER MODEL — 1H Bearish FVG Fill Short (BTC)","BTCUSDT","1h","Any","Bearish","Price fills a bearish FVG from above then continues lower — short entry as price taps imbalance.",[("1H bearish FVG identified and open",3.0,True),("Price approaches FVG from below (bounce)",2.5,True),("4H trend is bearish",2.5,False),("Bearish OB present within or near the FVG",2.0,False),("1H bearish candle reaction at FVG",2.0,False),("FVG in premium zone of the range",1.5,False),("Less than 3 previous tests of this FVG",1.5,False)]),
model("MM_FVG_03","MASTER MODEL — 4H FVG Magnet Long (BTC)","BTCUSDT","4h","Any","Bullish","Open 4H bullish FVG acting as a magnet below price — long entry when price sweeps down to fill it.",[("4H bullish FVG open below current price",3.0,True),("Price drops to test the 4H FVG",3.0,True),("4H trend is bullish overall",2.5,False),("1H bullish reaction when FVG is touched",2.5,False),("FVG aligns with 4H OB",2.0,False),("BTC dominance stable (no major alt season)",1.0,False),("Volume dry on the drop into FVG",1.5,False)]),
model("MM_FVG_04","MASTER MODEL — Nested FVG Bullish (15M inside 1H)","BTCUSDT","15m","London","Bullish","15M FVG nested inside a 1H FVG — double imbalance confluence for maximum precision entries.",[("1H bullish FVG identified and open",3.0,True),("15M bullish FVG nested within the 1H FVG",3.0,True),("4H bias is bullish",2.5,False),("London session active",1.5,False),("15M bullish OB within nested FVG",2.0,False),("Price enters from above (pullback not reversal)",2.0,False),("15M bullish reaction candle at entry",1.5,False)]),
model("MM_FVG_05","MASTER MODEL — Nested FVG Bearish (15M inside 1H)","ETHUSDT","15m","NY","Bearish","15M FVG nested inside a 1H bearish FVG — maximum precision short entries on ETH.",[("1H bearish FVG identified and open",3.0,True),("15M bearish FVG nested within the 1H FVG",3.0,True),("4H bias is bearish",2.5,False),("NY session active",1.5,False),("15M bearish OB within nested FVG",2.0,False),("Price bounces into zone from below",2.0,False),("15M bearish reaction candle at entry",1.5,False)]),
# Category 6
model("MM_SES_01","MASTER MODEL — London Open Bullish (BTC 15M)","BTCUSDT","15m","London","Bullish","London open manipulation then drive — buy the stop hunt in the first 30 minutes of London.",[("London session opened in last 30 minutes",3.0,True),("Price sweeps Asian session low at London open",3.0,True),("15M bullish reversal after the sweep",2.5,False),("4H bias is bullish",2.0,False),("15M bullish OB formed at sweep level",2.0,False),("Volume spike at the sweep",1.5,False),("Previous day had clear directional bias",1.5,False)]),
model("MM_SES_02","MASTER MODEL — London Open Bearish (BTC 15M)","BTCUSDT","15m","London","Bearish","London open takes Asian highs then drives lower — short the stop hunt in first 30 minutes of London.",[("London session opened in last 30 minutes",3.0,True),("Price sweeps Asian session high at London open",3.0,True),("15M bearish reversal after the sweep",2.5,False),("4H bias is bearish",2.0,False),("15M bearish OB formed at sweep level",2.0,False),("Volume spike at the sweep",1.5,False),("Previous day had clear directional bias",1.5,False)]),
model("MM_SES_03","MASTER MODEL — NY Open Continuation Bullish (BTC 15M)","BTCUSDT","15m","NY","Bullish","NY session confirms London direction and continues bullish — entry on NY open pullback.",[("London session closed bullish",2.5,True),("NY open pulls back to London OB or FVG",3.0,True),("15M bullish structure intact",2.5,False),("4H bias is bullish",2.0,False),("15M bullish OB at NY pullback level",2.0,False),("Volume increases on NY open",1.5,False),("NY open within first hour",1.5,False)]),
model("MM_SES_04","MASTER MODEL — NY Open Reversal Bearish (Gold 15M)","XAUUSD","15m","NY","Bearish","NY reverses London bullish move on Gold — NY open takes London highs then drives lower.",[("London session drove Gold higher",2.5,True),("NY open sweeps London session high",3.0,True),("15M bearish reversal candle after sweep",2.5,False),("DXY showing bullish NY open",2.0,False),("15M bearish OB at sweep zone",2.0,False),("Gold at 4H resistance or OB zone",1.5,False),("Volume spike on the sweep",1.5,False)]),
model("MM_SES_05","MASTER MODEL — Overlap Session Scalp Bullish (5M)","BTCUSDT","5m","Overlap","Bullish","London-NY overlap creates the highest volume period — 5M scalp longs during peak session overlap.",[("London-NY overlap active (13:00-16:00 UTC)",3.0,True),("4H and 1H bias both bullish",2.5,True),("5M bullish OB respected",2.5,False),("5M MSS to bullish",2.5,False),("5M FVG as target above entry",2.0,False),("Volume above average for the session",1.5,False),("BTC leading not lagging",1.0,False)]),
model("MM_SES_06","MASTER MODEL — Asia Session Range Short (BTC 1H)","BTCUSDT","1h","Asia","Bearish","Asia session establishes a range then fails at the top — short the range high during Asian hours.",[("Asia session active",2.0,True),("1H range clearly established in Asia",2.5,True),("Price rejects at the Asia range high",3.0,True),("Bearish OB at the range high",2.5,False),("4H bias is bearish or ranging",2.0,False),("Multiple tests of range high showing resistance",2.0,False),("1H bearish candle at rejection",1.5,False)]),
# Category 7
model("MM_MP_01","MASTER MODEL — BTC/ETH Correlation Long (ETH 1H)","ETHUSDT","1h","Any","Bullish","ETH lags BTC bullish move — enter ETH long when BTC has already confirmed and ETH is catching up.",[("BTC has already broken a key 1H high",3.0,True),("ETH has not yet broken its equivalent 1H high",2.5,True),("ETH 1H structure is bullish",2.5,False),("ETH at 1H bullish OB or FVG",2.0,False),("BTC not showing reversal signs",2.0,False),("ETH/BTC ratio at support level",2.0,False),("Session has high volume (London or NY)",1.5,False)]),
model("MM_MP_02","MASTER MODEL — Altcoin Season SOL Long (4H)","SOLUSDT","4h","Any","Bullish","SOL outperformance play when ETH and BTC are bullish and alts are gaining dominance.",[("BTC 4H trend is bullish",2.5,True),("ETH 4H trend is bullish",2.5,True),("SOL/BTC ratio breaking out",2.5,False),("SOL 4H bullish OB respected",2.0,False),("Total crypto market cap trending up",2.0,False),("SOL at key 4H support or FVG",2.0,False),("No major negative BTC news catalyst",1.5,False)]),
model("MM_MP_03","MASTER MODEL — Gold Safe Haven Long (1H)","XAUUSD","1h","London","Bullish","Gold long when risk-off environment detected — equities falling, dollar mixed, gold demand rising.",[("Gold 4H trend is bullish",3.0,True),("DXY not showing strong bullish impulse",2.5,True),("Gold 1H bullish OB in play",2.5,False),("Gold sweeps 1H lows then reverses",2.0,False),("1H FVG present at entry zone",2.0,False),("London session active",1.5,False),("Gold making higher highs on 4H",1.5,False)]),
# Category 8
model("MM_HTF_01","MASTER MODEL — Weekly Bullish Continuation (BTC)","BTCUSDT","1d","Any","Bullish","Swing long model using weekly and daily structure for multi-day to multi-week positions.",[("Weekly trend is bullish",4.0,True),("Daily structure is bullish",3.5,True),("Price pulls back to daily demand zone or OB",3.0,False),("Daily FVG present at demand zone",2.5,False),("Weekly RSI between 40-60 (pullback not exhaustion)",2.0,False),("Daily closes above the OB showing demand",2.0,False),("Monthly bias is bullish",2.0,False)]),
model("MM_HTF_02","MASTER MODEL — Weekly Bearish Continuation (BTC)","BTCUSDT","1d","Any","Bearish","Swing short model using weekly and daily structure for multi-day positions in downtrends.",[("Weekly trend is bearish",4.0,True),("Daily structure is bearish",3.5,True),("Price bounces to daily supply zone or OB",3.0,False),("Daily FVG present at supply zone",2.5,False),("Weekly RSI between 40-60 (bounce not oversold)",2.0,False),("Daily closes below the OB",2.0,False),("Monthly bias is bearish",2.0,False)]),
model("MM_HTF_03","MASTER MODEL — Monthly Level Reaction Long (BTC)","BTCUSDT","1d","Any","Bullish","Major monthly support level reaction — high conviction long at historically significant levels.",[("Monthly support level clearly identified",4.0,True),("Price at or within 2% of monthly support",3.5,True),("Daily bullish OB at monthly level",3.0,False),("Daily MSS to bullish confirmed",2.5,False),("Weekly RSI below 40 showing oversold conditions",2.0,False),("Volume spike on the daily reversal candle",2.0,False),("4H bullish structure forming",2.0,False)]),
# Category 9
model("MM_FX_01","MASTER MODEL — GBP/USD Bullish London (1H)","GBPUSD","1h","London","Bullish","Cable long entries during London session using OB, FVG, and DXY weakness confluence.",[("GBPUSD 4H trend is bullish",3.0,True),("London session sweeps Asian lows then reverses",2.5,True),("1H bullish OB at sweep level",2.5,False),("DXY showing 1H bearish structure",2.0,False),("1H bullish FVG present",2.0,False),("EURUSD also showing bullish London reaction",1.5,False),("UK session volume above average",1.5,False)]),
model("MM_FX_02","MASTER MODEL — EUR/USD Bearish NY (1H)","EURUSD","1h","NY","Bearish","EUR/USD short during NY session when DXY is strengthening and London bullish move is reversing.",[("EURUSD 4H structure is bearish",3.0,True),("NY open sweeps London session high",3.0,True),("1H bearish OB at the sweep",2.5,False),("DXY showing 1H bullish structure",2.5,False),("1H bearish FVG present",2.0,False),("GBPUSD also showing bearish NY reaction",1.5,False)]),
model("MM_FX_03","MASTER MODEL — Dollar Strength Short EUR (4H)","EURUSD","4h","Any","Bearish","Macro dollar strength model — shorts EUR/USD at 4H supply when DXY is in an uptrend.",[("DXY 4H trend is bullish",3.5,True),("EURUSD 4H trend is bearish",3.0,True),("EURUSD bounces into 4H bearish OB",2.5,False),("DXY at 4H bullish OB or demand zone",2.5,False),("EURUSD 4H FVG below entry as target",2.0,False),("No major ECB news in next 24 hours",1.5,False)]),
# Category 10
model("MM_ADV_01","MASTER MODEL — Optimal Trade Entry Bullish (15M)","BTCUSDT","15m","London","Bullish","ICT Optimal Trade Entry — price enters the 50% to 79% retracement of a bullish OB for OTE long.",[("4H bullish impulse move identified",3.0,True),("Price retraces to 50-79% of the impulse",3.0,True),("15M bullish OB within the OTE zone",2.5,False),("15M FVG within OTE zone",2.5,False),("4H bias is bullish",2.0,False),("London session for volume",1.5,False),("15M bullish reaction candle at OTE",2.0,False)]),
model("MM_ADV_02","MASTER MODEL — Optimal Trade Entry Bearish (15M)","BTCUSDT","15m","London","Bearish","ICT OTE short — price retraces into the 50-79% of a bearish impulse for OTE short entry.",[("4H bearish impulse move identified",3.0,True),("Price retraces to 50-79% of the impulse",3.0,True),("15M bearish OB within OTE zone",2.5,False),("15M FVG within OTE zone",2.5,False),("4H bias is bearish",2.0,False),("London session for volume",1.5,False),("15M bearish reaction candle at OTE",2.0,False)]),
model("MM_ADV_03","MASTER MODEL — Power of Three Bullish (1H)","BTCUSDT","1h","London","Bullish","ICT Power of Three — accumulation, manipulation, distribution on the daily candle — buy the manipulation.",[("Daily candle in accumulation phase (opens and holds level)",3.0,True),("London session creates the manipulation drop",3.0,True),("Price sweeps previous day low at London open",2.5,False),("1H bullish OB at manipulation low",2.5,False),("4H bias is bullish for the day",2.0,False),("1H bullish reversal candle after manipulation",2.0,False),("FVG left by the reversal impulse",1.5,False)]),
model("MM_ADV_04","MASTER MODEL — Power of Three Bearish (1H)","BTCUSDT","1h","London","Bearish","ICT Power of Three bearish day — buy the manipulation high then distribute all day.",[("Daily candle in accumulation phase",3.0,False),("London session creates manipulation rally",3.0,True),("Price sweeps previous day high at London open",2.5,True),("1H bearish OB at manipulation high",2.5,False),("4H bias is bearish for the day",2.0,False),("1H bearish reversal candle after manipulation",2.0,False),("FVG left below by reversal impulse",1.5,False)]),
model("MM_ADV_05","MASTER MODEL — Judas Swing Bullish (15M)","XAUUSD","15m","London","Bullish","Judas swing — London creates a fake bearish move that stops retail traders out before the real move up.",[("London session active",2.5,True),("Price drops aggressively in first 30 min of London",3.0,True),("The drop sweeps a key support or equal lows",3.0,True),("Rapid reversal candle after the sweep",2.5,False),("15M bullish OB at the Judas swing low",2.0,False),("4H daily bias is bullish for the day",2.0,False),("15M FVG left by reversal",1.5,False)]),
model("MM_ADV_06","MASTER MODEL — Silver Bullet Bullish (5M)","BTCUSDT","5m","NY","Bullish","ICT Silver Bullet — 10:00-11:00 AM NY time FVG entry for precision 5-minute scalp longs.",[("Time between 15:00-16:00 UTC (10-11 AM NY)",3.5,True),("5M bullish FVG forms in this window",3.5,True),("Price pulls back to fill the FVG",2.5,False),("4H and 1H bias both bullish",2.5,False),("5M bullish OB within or at FVG",2.0,False),("NY session volume above average",1.5,False)]),
model("MM_ADV_07","MASTER MODEL — Silver Bullet Bearish (5M)","BTCUSDT","5m","NY","Bearish","ICT Silver Bullet bearish — 10-11 AM NY bearish FVG for precision short scalps.",[("Time between 15:00-16:00 UTC",3.5,True),("5M bearish FVG forms in this window",3.5,True),("Price bounces to fill the FVG",2.5,False),("4H and 1H bias both bearish",2.5,False),("5M bearish OB within or at FVG",2.0,False),("NY session volume above average",1.5,False)]),
model("MM_ADV_08","MASTER MODEL — Midnight Open Bullish (1H)","BTCUSDT","1h","Any","Bullish","Midnight NY open creates a key reference point — price returns to midnight open level for long entries.",[("Midnight NY open level identified (00:00 EST)",3.0,True),("Price pulls back to midnight open level",3.0,True),("1H bullish OB at midnight open",2.5,False),("Daily bias is bullish",2.5,False),("1H FVG near midnight open level",2.0,False),("Prior price action shows midnight level as key",1.5,False),("1H bullish reaction at the level",1.5,False)]),
model("MM_ADV_09","MASTER MODEL — HTF Bias LTF Expansion 3R (5M)","BTCUSDT","5m","Any","Bullish","High-selectivity 3R model: trades only with clear HTF trend context and LTF momentum expansion after pullback.",[("HTF 4H trend clearly aligned",3.5,True),("HTF 1H structure confirms trend continuation",3.0,True),("LTF 5M pullback into premium/discount zone complete",2.5,True),("LTF 5M displacement candle closes beyond structure",3.5,True),("Liquidity sweep occurs before expansion",2.5,False),("Volume expansion above average on trigger candle",2.5,False),("Fresh OB/FVG confluence at entry",2.0,False),("Session overlap or NY volatility window",1.5,False)], rr_target=3.0),
]


def ensure_schema(cur):
    cur.execute("""
    ALTER TABLE models
    ADD COLUMN IF NOT EXISTS description TEXT,
    ADD COLUMN IF NOT EXISTS session VARCHAR(20) DEFAULT 'Any',
    ADD COLUMN IF NOT EXISTS bias VARCHAR(10) DEFAULT 'Bullish',
    ADD COLUMN IF NOT EXISTS min_score FLOAT,
    ADD COLUMN IF NOT EXISTS tier_a_threshold FLOAT,
    ADD COLUMN IF NOT EXISTS tier_b_threshold FLOAT,
    ADD COLUMN IF NOT EXISTS tier_c_threshold FLOAT,
    ADD COLUMN IF NOT EXISTS tier_a FLOAT DEFAULT 0,
    ADD COLUMN IF NOT EXISTS tier_b FLOAT DEFAULT 0,
    ADD COLUMN IF NOT EXISTS tier_c FLOAT DEFAULT 0,
    ADD COLUMN IF NOT EXISTS rr_target FLOAT DEFAULT 2.0;
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS model_rules (
        id VARCHAR(100) PRIMARY KEY,
        model_id VARCHAR(50) NOT NULL REFERENCES models(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        weight FLOAT NOT NULL,
        mandatory BOOLEAN NOT NULL DEFAULT FALSE,
        description TEXT
    );
    """)


def run():
    conn_check = db.get_conn()
    try:
        with conn_check.cursor() as cur_check:
            cur_check.execute("SELECT COUNT(*) FROM models")
            count_row = cur_check.fetchone()
            count = count_row["count"] if isinstance(count_row, dict) else count_row[0]
            print(f"Connected. models table has {count} existing rows.")

            cur_check.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'models'
                ORDER BY ordinal_position
            """)
            col_rows = cur_check.fetchall()
            columns = [
                row["column_name"] if isinstance(row, dict) else row[0]
                for row in col_rows
            ]
            print(f"Table columns: {columns}")
    finally:
        db.release_conn(conn_check)

    conn = psycopg2.connect(DB_URL)
    conn.autocommit = False
    cur = conn.cursor()
    ensure_schema(cur)
    conn.commit()

    inserted = 0
    for model in MODELS:
        values = (
            model["id"],
            model["name"],
            model["pair"],
            model["timeframe"],
            model["session"],
            model["bias"],
            model["status"],
            json.dumps(model["rules"]),
            model["tier_a_threshold"],
            model["tier_b_threshold"],
            model["tier_c_threshold"],
            model["min_score"],
                model["description"],
                model["tier_a"],
                model["tier_b"],
                model["tier_c"],
                model.get("rr_target", 2.0),
            )
        try:
            cur.execute("""
                INSERT INTO models
                (id, name, pair, timeframe, session, bias, status,
                 rules, tier_a_threshold, tier_b_threshold,
                 tier_c_threshold, min_score, description, tier_a, tier_b, tier_c, rr_target)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    pair = EXCLUDED.pair,
                    timeframe = EXCLUDED.timeframe,
                    session = EXCLUDED.session,
                    bias = EXCLUDED.bias,
                    status = EXCLUDED.status,
                    rules = EXCLUDED.rules,
                    tier_a_threshold = EXCLUDED.tier_a_threshold,
                    tier_b_threshold = EXCLUDED.tier_b_threshold,
                    tier_c_threshold = EXCLUDED.tier_c_threshold,
                    min_score = EXCLUDED.min_score,
                    description = EXCLUDED.description,
                    tier_a = EXCLUDED.tier_a,
                    tier_b = EXCLUDED.tier_b,
                    tier_c = EXCLUDED.tier_c,
                    rr_target = EXCLUDED.rr_target
            """, values)
            conn.commit()
            inserted += 1
            print(f"[OK] Inserted: {model['id']}")
            for rule in model["rules"]:
                cur.execute(
                    """
                    INSERT INTO model_rules (id, model_id, name, weight, mandatory, description)
                    VALUES (%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (id) DO UPDATE SET
                        name = EXCLUDED.name,
                        weight = EXCLUDED.weight,
                        mandatory = EXCLUDED.mandatory,
                        description = EXCLUDED.description
                    """,
                    (rule["id"], model["id"], rule["name"], rule["weight"], rule["mandatory"], rule["description"]),
                )
            cur.execute(
                """
                INSERT INTO model_versions (model_id, version, snapshot)
                SELECT %s,1,%s::jsonb
                WHERE NOT EXISTS (
                    SELECT 1 FROM model_versions WHERE model_id=%s AND version=1
                )
                """,
                (model["id"], json.dumps(model), model["id"]),
            )
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"[FAIL] {model['id']} - {e}")
            print(f"   Values: {values}")

    cur.close()
    conn.close()

    print("[DONE] MASTER MODELS created:")
    print("Category 1 - Trend Continuation: 6 models")
    print("Category 2 - Reversal: 6 models")
    print("Category 3 - Liquidity Grab: 7 models")
    print("Category 4 - Order Block: 7 models")
    print("Category 5 - Fair Value Gap: 5 models")
    print("Category 6 - Session-Specific: 6 models")
    print("Category 7 - Multi-Pair: 3 models")
    print("Category 8 - HTF Swing: 3 models")
    print("Category 9 - Forex: 3 models")
    print("Category 10 - Advanced Concepts: 8 models")
    print("------------------------")
    print(f"Total: {inserted} MASTER MODELS inserted")
    print("All set to inactive - activate from the bot")


if __name__ == "__main__":
    run()
