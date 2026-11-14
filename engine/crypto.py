"""Crypto day trader (paper): chases coins that are pumping, every hour.

    python engine/crypto.py          # one check (the hourly cloud job)
    python engine/crypto.py --dry    # show what it would do, change nothing

Prices are Coinbase's free public market data: live, every coin listed in USD,
meme coins included. No orders go anywhere. Like the other shadow books it is
a ledger (trader/engine/crypto.json, trades in crypto_trades.csv), and every
buy and sell pays 0.5% for fees and spread, which is what a small account
really pays on these coins. Results are on CRYPTO.md.

Rules, fixed before the first run and not tuned:
  scan   every USD coin on Coinbase with at least $1M traded in 24 hours,
         stablecoins left out
  buy    up at least 8% in 24 hours, the last full hour closed above the
         previous 6 hours' high on at least twice the usual hourly volume,
         and still within 10% of its 24-hour high. Strongest first.
  size   20% of the book per coin, at most 5 coins at once
  sell   10% below the highest price since buying (a trailing stop, which is
         also the stop loss), or after 24 hours, whichever comes first.
         The stop is checked against every hourly candle, so it acts like a
         stop order resting at the exchange.
  wait   no buying the same coin again for 24 hours after selling it
Benchmarks over the same dates: just holding Bitcoin, and just holding a basket
of meme coins. If the trader cannot beat holding the same kind of coins, the
trading itself adds nothing.
"""
import argparse
import datetime
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, STATE_DIR  # noqa: E402

API = "https://api.coinbase.com/api/v3/brokerage/market"
LEDGER = os.path.join(STATE_DIR, "crypto.json")
TRADES = os.path.join(STATE_DIR, "crypto_trades.csv")
PAGE = os.path.join(ROOT, "CRYPTO.md")

START_CASH = 10000.0
COST = 0.005            # per side: fee plus spread
MIN_VOLUME = 1e6        # dollars traded in 24 hours
PUMP_24H = 8.0          # percent
NEAR_HIGH = 0.90        # price at least 90% of the 24-hour high
BREAKOUT_HOURS = 6
VOLUME_SURGE = 2.0
SLOT = 0.20             # share of the book per coin
MAX_COINS = 5
TRAIL = 0.10            # sell 10% under the peak since buying
MAX_HOLD = 24 * 3600
COOLDOWN = 24 * 3600
STABLES = {"USDT", "USDC", "DAI", "PYUSD", "EURC", "USDS", "GUSD", "PAX", "USD1", "FDUSD", "TUSD", "RLUSD",
           "USDP", "EURT", "GYEN", "LUSD", "FRAX"}
MEMES = ["DOGE", "SHIB", "PEPE", "BONK", "WIF", "FLOKI", "TRUMP", "PENGU", "FARTCOIN", "SPX", "POPCAT",
         "PNUT", "TURBO", "MOG"]


def get(path):
    for attempt in range(3):
        try:
            req = urllib.request.Request(API + path, headers={"User-Agent": "ai-trader"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception:   # noqa: BLE001
            if attempt == 2:
                raise
            time.sleep(2 + 2 * attempt)


def products():
    """{product_id: product} for every online USD spot pair."""
    out = {}
    for p in get("/products?product_type=SPOT").get("products", []):
        if p.get("quote_currency_id") != "USD" or p.get("status") != "online" or p.get("trading_disabled") \
                or p.get("is_disabled") or p.get("cancel_only") or not p.get("price"):
            continue
        out[p["product_id"]] = p
    return out


def candles(pid, since):
    """Hourly candles from `since` (unix) to now, oldest first, as floats."""
    now = int(time.time())
    rows = get("/products/%s/candles?start=%d&end=%d&granularity=ONE_HOUR" % (pid, int(since), now)).get("candles", [])
    out = [{k: float(c[k]) for k in ("start", "open", "high", "low", "close", "volume")} for c in rows]
    return sorted(out, key=lambda c: c["start"])


def _f(p, k):
    try:
        return float(p.get(k) or 0)
    except (TypeError, ValueError):
        return 0.0


def stamp(t):
    return datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")


def record(row):
    new = not os.path.exists(TRADES)
    with open(TRADES, "a", encoding="utf-8") as fh:
        if new:
            fh.write("time_utc,side,coin,price,qty,usd,reason,pnl_usd,pnl_pct\n")
        fh.write("%s,%s,%s,%.10g,%.10g,%.2f,%s,%s,%s\n" % (
            stamp(row["t"]), row["side"], row["coin"], row["price"], row["qty"], row["usd"], row["reason"],
            "" if row.get("pnl") is None else "%.2f" % row["pnl"],
            "" if row.get("pnl_pct") is None else "%.2f" % row["pnl_pct"]))


def new_ledger(px):
    t = time.time()
    memes = [m + "-USD" for m in MEMES if m + "-USD" in px]
    return {"start": {"t": t, "cash": START_CASH},
            "cash": START_CASH, "positions": {}, "cooldown": {},
            "bench": {"btc": {"BTC-USD": START_CASH / px["BTC-USD"]},
                      "memes": {m: START_CASH / len(memes) / px[m] for m in memes}},
            "stats": {"trades": 0, "wins": 0, "fees": 0.0}}


def value(ledger, px):
    return ledger["cash"] + sum(p["qty"] * px.get(c, p["entry"]) for c, p in ledger["positions"].items())


def check_exits(ledger, px, now, dry, out):
    for coin, pos in list(ledger["positions"].items()):
        peak, exit_px, reason, when = pos["entry"], None, None, now
        for c in candles(coin, pos["t"]):
            if c["start"] < pos["t"]:
                continue   # the hour we bought in is only partly ours; the live price covers it
            stop = peak * (1 - TRAIL)
            if c["low"] <= stop:
                exit_px, reason, when = min(stop, c["open"]), "trailing stop", c["start"]
                break
            peak = max(peak, c["high"])
        if exit_px is None:
            last = px.get(coin, peak)
            if last <= peak * (1 - TRAIL):
                exit_px, reason = last, "trailing stop"
            elif now - pos["t"] >= MAX_HOLD:
                exit_px, reason = last, "24 hours up"
        pos["peak"] = peak
        if exit_px is None:
            continue
        got = pos["qty"] * exit_px * (1 - COST)
        pnl = got - pos["cost"]
        out("  SELL %-13s at %.6g (%s): %+.1f%%, $%+.2f" % (coin, exit_px, reason, pnl / pos["cost"] * 100, pnl))
        if dry:
            continue
        ledger["cash"] += got
        ledger["stats"]["trades"] += 1
        ledger["stats"]["wins"] += pnl > 0
        ledger["stats"]["fees"] += pos["qty"] * exit_px * COST
        ledger["cooldown"][coin] = when + COOLDOWN
        del ledger["positions"][coin]
        record({"t": when, "side": "sell", "coin": coin, "price": exit_px, "qty": pos["qty"], "usd": got,
                "reason": reason, "pnl": pnl, "pnl_pct": pnl / pos["cost"] * 100})


def candidates(prods, ledger, now):
    out = []
    for pid, p in prods.items():
        base = p.get("base_currency_id", "")
        if base in STABLES or "USD" in base or pid in ledger["positions"]:
            continue
        if ledger["cooldown"].get(pid, 0) > now:
            continue
        price, chg, hi = _f(p, "price"), _f(p, "price_percentage_change_24h"), _f(p, "high_24h")
        vol = _f(p, "approximate_quote_24h_volume")
        if vol >= MIN_VOLUME and chg >= PUMP_24H and (not hi or price >= NEAR_HIGH * hi):
            out.append((chg, pid))
    return [pid for _chg, pid in sorted(out, reverse=True)]


def check_entries(ledger, prods, px, now, dry, out):
    slots = MAX_COINS - len(ledger["positions"])
    if slots <= 0:
        return
    looked = []
    for pid in candidates(prods, ledger, now)[:12]:
        if slots <= 0:
            break
        cs = [c for c in candles(pid, now - 30 * 3600) if c["start"] + 3600 <= now]   # finished hours only
        if len(cs) < BREAKOUT_HOURS + 2:
            continue
        last, prev = cs[-1], cs[-1 - BREAKOUT_HOURS:-1]
        vols = sorted(c["volume"] for c in cs[-25:-1])
        usual = vols[len(vols) // 2] if vols else 0
        breakout = last["close"] > max(c["high"] for c in prev)
        surge = usual > 0 and last["volume"] >= VOLUME_SURGE * usual
        looked.append("%s %+.0f%%%s%s" % (pid, _f(prods[pid], "price_percentage_change_24h"),
                                          "" if breakout else " no-breakout", "" if surge else " no-volume"))
        if not (breakout and surge):
            continue
        equity = value(ledger, px)
        spend = min(SLOT * equity, ledger["cash"])
        if spend < 50:
            break
        price = px[pid] * (1 + COST)
        qty = spend / price
        out("  BUY  %-13s at %.6g for $%.2f (%+.1f%% in 24h, breakout on %.1fx volume)" % (
            pid, px[pid], spend, _f(prods[pid], "price_percentage_change_24h"), last["volume"] / usual))
        slots -= 1
        if dry:
            continue
        ledger["cash"] -= spend
        ledger["stats"]["fees"] += spend - qty * px[pid]
        ledger["positions"][pid] = {"qty": qty, "entry": px[pid], "t": now, "cost": spend, "peak": px[pid]}
        record({"t": now, "side": "buy", "coin": pid, "price": px[pid], "qty": qty, "usd": spend,
                "reason": "pump %+.1f%%" % _f(prods[pid], "price_percentage_change_24h")})
    if looked:
        out("  looked at: " + ", ".join(looked))


def page(ledger, px, now):
    v = value(ledger, px)
    b = sum(q * px.get(c, 0) for c, q in ledger["bench"]["btc"].items())
    m = sum(q * px.get(c, 0) for c, q in ledger["bench"]["memes"].items())
    s = ledger["stats"]
    rows = [("Meme-coin day trader", v), ("Just hold Bitcoin", b), ("Just hold %d meme coins" % len(
        ledger["bench"]["memes"]), m)]
    out = ["# Crypto day trader", "",
           "Paper money, $%s each, started %s UTC. Updated %s UTC. Prices: Coinbase, live." % (
               format(START_CASH, ",.0f"), stamp(ledger["start"]["t"]), stamp(now)), "",
           "| Player | Value | Return |", "| --- | --- | --- |"]
    for name, val in sorted(rows, key=lambda r: -r[1]):
        out.append("| %s | $%s | **%+.2f%%** |" % (name, format(val, ",.2f"), (val / START_CASH - 1) * 100))
    out += ["", "Closed trades: %d, winners: %d (%s). Fees and spread paid: $%s." % (
        s["trades"], s["wins"], ("%.0f%%" % (100.0 * s["wins"] / s["trades"])) if s["trades"] else "n/a",
        format(s["fees"], ",.2f")), "", "## Holding now", ""]
    if ledger["positions"]:
        out += ["| Coin | Bought (UTC) | Entry | Now | P&L | Sells below | Sells by |",
                "| --- | --- | --- | --- | --- | --- | --- |"]
        for c, p in ledger["positions"].items():
            now_px = px.get(c, p["entry"])
            out.append("| %s | %s | %.6g | %.6g | %+.1f%% | %.6g | %s |" % (
                c, stamp(p["t"]), p["entry"], now_px, (now_px * (1 - COST) * p["qty"] / p["cost"] - 1) * 100,
                p.get("peak", p["entry"]) * (1 - TRAIL), stamp(p["t"] + MAX_HOLD)))
    else:
        out.append("Nothing. Cash, waiting for a coin that pumps.")
    out += ["", "## Last trades", "", "| Time (UTC) | Side | Coin | Price | $ | Why | P&L |", "| --- | --- | --- | --- | --- | --- | --- |"]
    if os.path.exists(TRADES):
        lines = open(TRADES, encoding="utf-8").read().splitlines()[1:]
        for line in reversed(lines[-20:]):
            t, side, coin, price, _q, usd, why, pnl, pct = line.split(",")
            out.append("| %s | %s | %s | %s | %s | %s | %s |" % (
                t, side, coin, price, usd, why, ("$%s (%s%%)" % (pnl, pct)) if pnl else ""))
    out += ["", "Rules are in `engine/crypto.py`. Most people who day-trade meme coins lose money; "
            "this page shows whether this rulebook does too."]
    with open(PAGE, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out) + "\n")
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    now = time.time()
    prods = products()
    px = {pid: _f(p, "price") for pid, p in prods.items()}
    ledger = json.load(open(LEDGER, encoding="utf-8")) if os.path.exists(LEDGER) else new_ledger(px)
    print("Crypto check %s UTC, %d coins listed, %d holding" % (stamp(now), len(prods), len(ledger["positions"])))
    check_exits(ledger, px, now, a.dry, print)
    check_entries(ledger, prods, px, now, a.dry, print)
    ledger["cooldown"] = {c: t for c, t in ledger["cooldown"].items() if t > now}
    if a.dry:
        return
    os.makedirs(STATE_DIR, exist_ok=True)
    peaks = {c: p.pop("peak", None) for c, p in ledger["positions"].items()}   # peaks are recomputed every run
    json.dump(ledger, open(LEDGER, "w", encoding="utf-8"), indent=1)
    for c, pk in peaks.items():
        ledger["positions"][c]["peak"] = pk
    for name, val in page(ledger, px, now):
        print("  %-26s $%s  %+.2f%%" % (name, format(val, ",.2f"), (val / START_CASH - 1) * 100))


if __name__ == "__main__":
    main()
