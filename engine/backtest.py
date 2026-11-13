"""Replay the strategy over real history and compare it with doing nothing clever.

    python engine/backtest.py

A decision made on one day's close is traded at the NEXT day's open, with a
cost charged on every dollar traded. Benchmarks: holding SPY, and holding every
stock in the universe equally (the fair one, because the universe is today's
big companies).
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import STATE_DIR, align, load_bars  # noqa: E402
from strategy import BENCH, ENSEMBLE, PARAMS, UNIVERSE, features, targets  # noqa: E402

COST = 0.001   # 0.10% of every dollar traded: spread and slippage on large stocks
START_I = 253


def simulate(dates, opens, closes, decide, every):
    """decide(i, held) -> weights. Returns (equity curve from START_I, yearly turnover)."""
    cash, shares, curve, pending, last, traded = 1.0, {}, [], None, -10 ** 9, 0.0
    for i in range(START_I, len(dates)):
        if pending is not None:
            equity = cash + sum(n * opens[s][i] for s, n in shares.items())
            new = {}
            moved = 0.0
            for s in set(shares) | set(pending):
                want = pending.get(s, 0.0) * equity
                have = shares.get(s, 0.0) * opens[s][i]
                moved += abs(want - have)
                if want > 0:
                    new[s] = want / opens[s][i]
            cash = equity - sum(n * opens[s][i] for s, n in new.items()) - moved * COST
            shares, traded, pending = new, traded + moved / equity, None
        curve.append(cash + sum(n * closes[s][i] for s, n in shares.items()))
        if i - last >= every and i < len(dates) - 1:
            pending, last = decide(i, list(shares)), i
    years = (len(dates) - START_I) / 252.0
    return curve, traded / years


def stats(curve):
    years = len(curve) / 252.0
    rets = [curve[k] / curve[k - 1] - 1 for k in range(1, len(curve))]
    mean = sum(rets) / len(rets)
    sd = (sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)) ** 0.5
    peak, worst = curve[0], 0.0
    for v in curve:
        peak = max(peak, v)
        worst = min(worst, v / peak - 1)
    return {"total": curve[-1] / curve[0] - 1, "cagr": (curve[-1] / curve[0]) ** (1 / years) - 1,
            "vol": sd * 252 ** 0.5, "sharpe": mean / sd * 252 ** 0.5 if sd else 0.0, "max_dd": worst}


def by_year(dates, curve):
    out, d = {}, dates[START_I:]
    for k in range(1, len(curve)):
        y = d[k][:4]
        out.setdefault(y, [curve[k - 1], curve[k]])[1] = curve[k]
    return {y: v[1] / v[0] - 1 for y, v in out.items()}


def main():
    bars = load_bars(UNIVERSE + [BENCH])
    missing = [s for s in UNIVERSE if s not in bars]
    dates, opens, closes = align(bars, BENCH)
    print("History: %s to %s, %d trading days, %d of %d stocks have data%s" % (
        dates[0], dates[-1], len(dates), len(UNIVERSE) - len(missing), len(UNIVERSE),
        (" (missing: %s)" % " ".join(missing)) if missing else ""))
    print("Tested from %s. Cost %.2f%% per dollar traded. Trades fill at the next open.\n"
          % (dates[START_I], COST * 100))

    runs = {}

    def strat(weights):
        return lambda i, held: targets(closes, i, held, weights)[0]

    runs["ENSEMBLE (all signals vote)"] = simulate(dates, opens, closes, strat(ENSEMBLE),
                                                   PARAMS["rebalance_days"])
    for k in ENSEMBLE:
        runs["only " + k] = simulate(dates, opens, closes, strat({k: 1.0}), PARAMS["rebalance_days"])
    runs["SPY, buy and hold"] = simulate(dates, opens, closes, lambda i, h: {BENCH: 1.0}, 10 ** 9)

    def equal(i, held):
        names = [s for s in closes if s != BENCH and features(closes[s], i)]
        return {s: 1.0 / len(names) for s in names}
    runs["all ~100 stocks equally"] = simulate(dates, opens, closes, equal, 21)

    print("%-30s %9s %8s %8s %8s %9s %9s" % ("", "total", "per yr", "swings", "sharpe", "worst dd", "turnover"))
    table = {}
    for name, (curve, turn) in runs.items():
        s = stats(curve)
        table[name] = dict(s, turnover=turn, years=by_year(dates, curve))
        print("%-30s %8.0f%% %7.1f%% %7.1f%% %8.2f %8.1f%% %8.1fx" % (
            name, s["total"] * 100, s["cagr"] * 100, s["vol"] * 100, s["sharpe"], s["max_dd"] * 100, turn))

    names = ["ENSEMBLE (all signals vote)", "SPY, buy and hold", "all ~100 stocks equally"]
    print("\nYear by year:   %s" % "   ".join("%-12s" % n[:12] for n in names))
    wins_spy = wins_eq = n_years = 0
    for y in sorted(table[names[0]]["years"]):
        row = [table[n]["years"].get(y, 0.0) for n in names]
        n_years += 1
        wins_spy += row[0] > row[1]
        wins_eq += row[0] > row[2]
        print("  %s          %s" % (y, "   ".join("%+11.1f%%" % (v * 100) for v in row)))
    print("\nEnsemble beat SPY in %d of %d years, and beat equal-weight in %d of %d."
          % (wins_spy, n_years, wins_eq, n_years))

    os.makedirs(STATE_DIR, exist_ok=True)
    json.dump({"from": dates[START_I], "to": dates[-1], "cost": COST, "results": table},
              open(os.path.join(STATE_DIR, "backtest.json"), "w", encoding="utf-8"), indent=1)


if __name__ == "__main__":
    main()
