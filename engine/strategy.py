"""The decision: several independent signals vote, one portfolio comes out.

Every number here was fixed before the backtest was run and has not been tuned
to make the backtest look better. Both the backtest and the live runner call
`targets()`, so what was tested is what trades.
"""

BENCH = "SPY"

# About 100 of the largest US companies as of 2026. Picking today's winners
# flatters any backtest, so results are also compared against simply holding
# all of these equally (see backtest.py).
UNIVERSE = """AAPL ABBV ABT ACN ADBE AIG AMD AMGN AMT AMZN AVGO AXP BA BAC BK BKNG BLK BMY BRK.B C
CAT CHTR CL CMCSA COF COP COST CRM CSCO CVS CVX DE DHR DIS DUK EMR FDX GD GE GILD GM GOOGL GS HD
HON IBM INTC INTU ISRG JNJ JPM KO LIN LLY LMT LOW MA MCD MDLZ MDT MET META MMM MO MRK MS MSFT NEE
NFLX NKE NOW NVDA ORCL PEP PFE PG PLTR PM PYPL QCOM RTX SBUX SCHW SO SPG T TGT TMO TMUS TSLA TXN
UNH UNP UPS USB V VZ WFC WMT XOM""".split()

PARAMS = {
    "top_n": 10,               # stocks held
    "keep_rank": 20,           # a holding stays until it drops below this rank
    "max_weight": 0.15,        # cap per stock
    "rebalance_days": 5,       # trading days between rebalances (weekly)
    "risk_off_exposure": 0.5,  # share invested when the market is below its 200-day average
}

# The votes. Each signal ranks every stock; the weights say how much each vote counts.
ENSEMBLE = {"momentum": 0.40, "trend": 0.20, "lowvol": 0.25, "reversal": 0.15}


def features(c, i):
    """Signals for one stock from closes up to and including day i. None = not enough history."""
    if i < 252 or c[i] is None or c[i - 252] is None:
        return None
    momentum = 0.5 * (c[i - 21] / c[i - 252] - 1) + 0.5 * (c[i - 21] / c[i - 126] - 1)
    trend = c[i] / (sum(c[i - 199:i + 1]) / 200.0) - 1
    rets = [c[k] / c[k - 1] - 1 for k in range(i - 59, i + 1)]
    mean = sum(rets) / len(rets)
    vol = (sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)) ** 0.5
    return {"momentum": momentum, "trend": trend, "lowvol": -vol,
            "reversal": -(c[i] / c[i - 5] - 1), "vol": max(vol, 1e-4)}


def _z(values):
    """Standard scores across stocks, clipped at 3 so one outlier cannot dominate."""
    xs = list(values.values())
    mean = sum(xs) / len(xs)
    sd = (sum((x - mean) ** 2 for x in xs) / max(len(xs) - 1, 1)) ** 0.5
    if sd == 0:
        return {k: 0.0 for k in values}
    return {k: max(-3.0, min(3.0, (v - mean) / sd)) for k, v in values.items()}


def risk_on(bench_closes, i):
    return bench_closes[i] > sum(bench_closes[i - 199:i + 1]) / 200.0


def targets(closes, i, held=(), weights=None, params=None):
    """Target weights for day i. Returns (weights by symbol, details)."""
    weights = weights or ENSEMBLE
    p = dict(PARAMS)
    p.update(params or {})
    feats = {}
    for sym, c in closes.items():
        if sym == BENCH:
            continue
        f = features(c, i)
        if f:
            feats[sym] = f
    if len(feats) < p["top_n"]:
        return {}, {"risk_on": True, "ranked": [], "votes": {}}
    z = {k: _z({s: f[k] for s, f in feats.items()}) for k in weights}
    score = {s: sum(w * z[k][s] for k, w in weights.items()) for s in feats}
    ranked = sorted(score, key=score.get, reverse=True)
    rank = {s: r for r, s in enumerate(ranked, 1)}

    picks = sorted([s for s in held if rank.get(s, 10 ** 9) <= p["keep_rank"]], key=rank.get)
    picks = picks[:p["top_n"]]
    for s in ranked:
        if len(picks) >= p["top_n"]:
            break
        if s not in picks:
            picks.append(s)

    # Steadier stocks get more money; nobody gets more than the cap.
    raw = {s: 1.0 / feats[s]["vol"] for s in picks}
    total = sum(raw.values())
    w = {s: v / total for s, v in raw.items()}
    for _ in range(20):
        over = [s for s in w if w[s] > p["max_weight"] + 1e-12]
        if not over:
            break
        free = [s for s in w if w[s] < p["max_weight"] - 1e-12]
        excess = sum(w[s] - p["max_weight"] for s in over)
        for s in over:
            w[s] = p["max_weight"]
        base = sum(w[s] for s in free)
        if not free or base <= 0:
            break
        for s in free:
            w[s] += excess * w[s] / base

    on = risk_on(closes[BENCH], i)
    exposure = 1.0 if on else p["risk_off_exposure"]
    out = {s: v * exposure for s, v in w.items()}
    votes = {s: {k: round(z[k][s], 2) for k in weights} for s in picks}
    return out, {"risk_on": on, "exposure": exposure, "ranked": ranked[:p["keep_rank"]],
                 "votes": votes, "score": {s: round(score[s], 3) for s in picks}}
