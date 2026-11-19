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
         The stop is checked against every 5-minute candle since buying, so it
         acts like a stop order resting at the exchange (a gap down fills at
         the open below the stop, as a real stop order would).
  wait   no buying the same coin again for 24 hours after selling it
Two traders run these rules side by side (TRADERS below). The second, added on
2026-11-18, also needs the coin to have been alive before the pump: at least $1M
a day on average over the week before the last 24 hours.
Benchmarks over each trader's own dates: just holding Bitcoin, and just holding
the meme coins that were alive (at least $1M a day on average in the week before
the start). If a trader cannot beat holding the same kind of coins, the trading
itself adds nothing.

A third trader (added 2026-11-18) is not a day trader: it follows the trend of
Bitcoin and Ethereum. Each coin gets at most half the book: a quarter of that half
for every one of its 20, 50, 100 and 200-day averages it closed above on the last
finished UTC day, cash for the rest. It trades when its target moves by at least
5% of the book. Using all four averages instead of the one that tested best avoids
picking a lucky number: on Coinbase daily prices from mid-2018 to 2026-11, with the
same 0.5% cost, it made 34%/yr with a worst drop of -53%, against 29%/yr and -77%
for holding Bitcoin. In the 2022 crash it lost 33% while Bitcoin lost 64%.
Benchmarks: just holding Bitcoin, and just holding half Bitcoin, half Ethereum.
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
ALIVE_DAYS = 7          # "alive" = at least MIN_VOLUME a day on average over the week before

# Two traders with the same rules, side by side. The second one (added 2026-11-18) only buys a
# pump when the coin was alive the week BEFORE it: the 24-hour volume test alone is passed by
# the pump's own volume, so the first one kept buying dead coins' one-off pumps (RARE traded
# $70k a day before its +74% pump). The first one keeps running unchanged so its record stays
# honest. The meme basket that both are compared with holds only meme coins alive by the same
# test, so dead coins do not drag it down.
TRADERS = [
    {"label": "Pump chaser, any coin", "kind": "pump", "ledger": LEDGER, "trades": TRADES, "alive_only": False},
    {"label": "Pump chaser, alive coins only", "kind": "pump", "ledger": os.path.join(STATE_DIR, "crypto_alive.json"),
     "trades": os.path.join(STATE_DIR, "crypto_alive_trades.csv"), "alive_only": True},
    {"label": "Trend: Bitcoin + Ethereum", "kind": "trend", "ledger": os.path.join(STATE_DIR, "crypto_trend.json"),
     "trades": os.path.join(STATE_DIR, "crypto_trend_trades.csv"), "alive_only": False},
]
TREND_COINS = ["BTC-USD", "ETH-USD"]
TREND_DAYS = (20, 50, 100, 200)
TREND_BAND = 0.05       # a move in the target smaller than 5% of the book is not worth the fees


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


STEP = {"ONE_HOUR": 3600, "FIVE_MINUTE": 300, "ONE_DAY": 86400}


def candles(pid, since, granularity="ONE_HOUR"):
    """Candles from `since` (unix) to now, oldest first, as floats. Coinbase returns at most
    350 per call, so longer spans are fetched in pieces of 300."""
    now, step = int(time.time()), STEP[granularity]
    got, start = {}, int(since)
    while start < now:
        end = min(now, start + 300 * step)
        rows = get("/products/%s/candles?start=%d&end=%d&granularity=%s" % (pid, start, end, granularity)).get(
            "candles", [])
        for c in rows:
            got[int(c["start"])] = {k: float(c[k]) for k in ("start", "open", "high", "low", "close", "volume")}
        start = end
    return [got[k] for k in sorted(got)]


def _f(p, k):
    try:
        return float(p.get(k) or 0)
    except (TypeError, ValueError):
        return 0.0


def stamp(t):
    return datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")


def avg_daily_volume(pid, end, days=ALIVE_DAYS):
    """Average dollars traded per day over the `days` days before `end` (unix)."""
    cs = [c for c in candles(pid, end - days * 86400) if c["start"] < end]
    return sum(c["volume"] * c["close"] for c in cs) / days


def alive_memes(px, end):
    """The meme coins that traded at least MIN_VOLUME a day on average in the week before `end`."""
    return [m + "-USD" for m in MEMES if m + "-USD" in px and avg_daily_volume(m + "-USD", end) >= MIN_VOLUME]


def record(path, row):
    new = not os.path.exists(path)
    with open(path, "a", encoding="utf-8") as fh:
        if new:
            fh.write("time_utc,side,coin,price,qty,usd,reason,pnl_usd,pnl_pct\n")
        fh.write("%s,%s,%s,%.10g,%.10g,%.2f,%s,%s,%s\n" % (
            stamp(row["t"]), row["side"], row["coin"], row["price"], row["qty"], row["usd"], row["reason"],
            "" if row.get("pnl") is None else "%.2f" % row["pnl"],
            "" if row.get("pnl_pct") is None else "%.2f" % row["pnl_pct"]))


def new_ledger(px, kind="pump"):
    t = time.time()
    bench = {"btc": {"BTC-USD": START_CASH / px["BTC-USD"]}}
    if kind == "trend":
        bench["pair"] = {c: START_CASH / len(TREND_COINS) / px[c] for c in TREND_COINS}
    else:
        memes = alive_memes(px, t) or [m + "-USD" for m in MEMES if m + "-USD" in px]
        bench["memes"] = {m: START_CASH / len(memes) / px[m] for m in memes}
    return {"start": {"t": t, "cash": START_CASH},
            "cash": START_CASH, "positions": {}, "cooldown": {}, "bench": bench,
            "stats": {"trades": 0, "wins": 0, "fees": 0.0}}


def value(ledger, px):
    return ledger["cash"] + sum(p["qty"] * px.get(c, p["entry"]) for c, p in ledger["positions"].items())


def check_exits(ledger, px, now, dry, out, trades):
    for coin, pos in list(ledger["positions"].items()):
        peak, exit_px, reason, when = pos["entry"], None, None, now
        # 5-minute candles from the moment of buying. Until 2026-11-16 this walked hourly candles and
        # skipped the hour of the buy, so a crash in the first hour was sold at the next hour's open
        # instead of at the stop (ASTER: -22.8% instead of about -11%).
        for c in candles(coin, pos["t"], "FIVE_MINUTE"):
            if c["start"] < pos["t"]:
                continue   # the 5 minutes we bought in are only partly ours
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
        record(trades, {"t": when, "side": "sell", "coin": coin, "price": exit_px, "qty": pos["qty"], "usd": got,
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


def check_entries(ledger, prods, px, now, dry, out, trades, alive_only, seen):
    """`seen` is shared by both traders in one run, so each coin is fetched once."""
    slots = MAX_COINS - len(ledger["positions"])
    if slots <= 0:
        return
    looked = []
    for pid in candidates(prods, ledger, now)[:12]:
        if slots <= 0:
            break
        if pid not in seen:
            cs = [c for c in candles(pid, now - 30 * 3600) if c["start"] + 3600 <= now]   # finished hours only
            seen[pid] = {"cs": cs}
        cs = seen[pid]["cs"]
        if len(cs) < BREAKOUT_HOURS + 2:
            continue
        last, prev = cs[-1], cs[-1 - BREAKOUT_HOURS:-1]
        vols = sorted(c["volume"] for c in cs[-25:-1])
        usual = vols[len(vols) // 2] if vols else 0
        breakout = last["close"] > max(c["high"] for c in prev)
        surge = usual > 0 and last["volume"] >= VOLUME_SURGE * usual
        note = "%s %+.0f%%%s%s" % (pid, _f(prods[pid], "price_percentage_change_24h"),
                                   "" if breakout else " no-breakout", "" if surge else " no-volume")
        if breakout and surge and alive_only:
            if "before" not in seen[pid]:   # the week before the last 24 hours, so the pump itself is left out
                seen[pid]["before"] = avg_daily_volume(pid, now - 86400)
            if seen[pid]["before"] < MIN_VOLUME:
                looked.append(note + " dead-before ($%.2fM/day)" % (seen[pid]["before"] / 1e6))
                continue
        looked.append(note)
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
        record(trades, {"t": now, "side": "buy", "coin": pid, "price": px[pid], "qty": qty, "usd": spend,
                        "reason": "pump %+.1f%%" % _f(prods[pid], "price_percentage_change_24h")})
    if looked:
        out("  looked at: " + ", ".join(looked))


def daily_closes(pid, now):
    """Closes of finished UTC days, oldest first."""
    return [c["close"] for c in candles(pid, now - 230 * 86400, "ONE_DAY") if c["start"] + 86400 <= now]


def trend_weights(now, out):
    """{coin: share of the book} from the last finished day's close against its four averages."""
    w, notes = {}, []
    for pid in TREND_COINS:
        x = daily_closes(pid, now)
        if len(x) < max(TREND_DAYS):
            notes.append("%s has too little history" % pid)
            continue
        above = [n for n in TREND_DAYS if x[-1] > sum(x[-n:]) / n]
        w[pid] = len(above) / float(len(TREND_DAYS)) / len(TREND_COINS)
        notes.append("%s above %d of 4 averages%s" % (
            pid.replace("-USD", ""), len(above), (" (%s days)" % "/".join(map(str, above))) if above else ""))
    out("  trend: " + "; ".join(notes))
    return w


def trend_step(ledger, px, now, dry, out, trades):
    want = trend_weights(now, out)
    ledger["target"] = want
    eq = value(ledger, px)
    orders = []
    for pid, share in want.items():
        pos = ledger["positions"].get(pid)
        have = pos["qty"] * px[pid] if pos else 0.0
        diff = share * eq - have
        if (share == 0 and have > 0) or abs(diff) >= TREND_BAND * eq:
            orders.append((diff, pid))
    for diff, pid in sorted(orders):   # sells first, so their cash is there for the buys
        pos = ledger["positions"].get(pid)
        why = "trend: %d of 4 averages" % round(want[pid] * len(TREND_COINS) * len(TREND_DAYS))
        if diff < 0:
            qty = pos["qty"] if want[pid] == 0 else min(pos["qty"], -diff / px[pid])
            got = qty * px[pid] * (1 - COST)
            basis = pos["cost"] * qty / pos["qty"]
            pnl = got - basis
            out("  SELL %-13s $%.2f at %.6g (%s): $%+.2f" % (pid, got, px[pid], why, pnl))
            if dry:
                continue
            ledger["cash"] += got
            ledger["stats"]["trades"] += 1
            ledger["stats"]["wins"] += pnl > 0
            ledger["stats"]["fees"] += qty * px[pid] * COST
            pos["qty"] -= qty
            pos["cost"] -= basis
            if want[pid] == 0 or pos["qty"] * px[pid] < 1:
                del ledger["positions"][pid]
            record(trades, {"t": now, "side": "sell", "coin": pid, "price": px[pid], "qty": qty, "usd": got,
                            "reason": why, "pnl": pnl, "pnl_pct": pnl / basis * 100})
        else:
            spend = min(diff, ledger["cash"])
            if spend < 50:
                continue
            qty = spend / (px[pid] * (1 + COST))
            out("  BUY  %-13s $%.2f at %.6g (%s)" % (pid, spend, px[pid], why))
            if dry:
                continue
            ledger["cash"] -= spend
            ledger["stats"]["fees"] += spend - qty * px[pid]
            if pos:
                pos["qty"] += qty
                pos["cost"] += spend
            else:
                ledger["positions"][pid] = {"qty": qty, "entry": px[pid], "t": now, "cost": spend}
            record(trades, {"t": now, "side": "buy", "coin": pid, "price": px[pid], "qty": qty, "usd": spend,
                            "reason": why})


def scores(trader, ledger, px):
    """[(name, value)] for the trader and its benchmarks over the same dates."""
    bench = ledger["bench"]
    rows = [(trader["label"], value(ledger, px)),
            ("Just hold Bitcoin", sum(q * px.get(c, 0) for c, q in bench["btc"].items()))]
    if "pair" in bench:
        rows.append(("Just hold half Bitcoin, half Ethereum", sum(q * px.get(c, 0) for c, q in bench["pair"].items())))
    if "memes" in bench:
        names = [c.replace("-USD", "") for c in bench["memes"]]
        rows.append(("Just hold %d alive meme coins (%s)" % (len(names), ", ".join(names)),
                     sum(q * px.get(c, 0) for c, q in bench["memes"].items())))
    return rows


def section(trader, ledger, px):
    s = ledger["stats"]
    if trader["kind"] == "trend":
        rule = ("Holds Bitcoin and Ethereum, at most half the book each: a quarter of that half for every one "
                "of the coin's 20, 50, 100 and 200-day averages it closed above yesterday, cash for the rest.")
    elif trader["alive_only"]:
        rule = "Buys a pump only if the coin traded at least $1M a day on average in the week before it."
    else:
        rule = "Buys any coin that pumps, even one that was dead before."
    out = ["## %s" % trader["label"], "",
           "Started %s UTC with $%s. %s" % (stamp(ledger["start"]["t"]), format(START_CASH, ",.0f"), rule), "",
           "| Player | Value | Return |", "| --- | --- | --- |"]
    for name, val in sorted(scores(trader, ledger, px), key=lambda r: -r[1]):
        out.append("| %s | $%s | **%+.2f%%** |" % (name, format(val, ",.2f"), (val / START_CASH - 1) * 100))
    out += ["", "Closed trades: %d, winners: %d (%s). Fees and spread paid: $%s." % (
        s["trades"], s["wins"], ("%.0f%%" % (100.0 * s["wins"] / s["trades"])) if s["trades"] else "n/a",
        format(s["fees"], ",.2f")), "", "Holding now:", ""]
    if trader["kind"] == "trend":
        eq = value(ledger, px)
        out += ["| Coin | Share of book | Target | Value | P&L |", "| --- | --- | --- | --- | --- |"]
        for c in TREND_COINS:
            p = ledger["positions"].get(c)
            val = p["qty"] * px.get(c, 0) if p else 0.0
            out.append("| %s | %.0f%% | %.1f%% | $%s | %s |" % (
                c, 100 * val / eq, 100 * ledger.get("target", {}).get(c, 0), format(val, ",.2f"),
                ("%+.1f%%" % ((val * (1 - COST) / p["cost"] - 1) * 100)) if p else ""))
        out.append("| cash | %.0f%% | | $%s | |" % (100 * ledger["cash"] / eq, format(ledger["cash"], ",.2f")))
    elif ledger["positions"]:
        out += ["| Coin | Bought (UTC) | Entry | Now | P&L | Sells below | Sells by |",
                "| --- | --- | --- | --- | --- | --- | --- |"]
        for c, p in ledger["positions"].items():
            now_px = px.get(c, p["entry"])
            out.append("| %s | %s | %.6g | %.6g | %+.1f%% | %.6g | %s |" % (
                c, stamp(p["t"]), p["entry"], now_px, (now_px * (1 - COST) * p["qty"] / p["cost"] - 1) * 100,
                p.get("peak", p["entry"]) * (1 - TRAIL), stamp(p["t"] + MAX_HOLD)))
    else:
        out.append("Nothing. Cash, waiting for a coin that pumps.")
    lines = open(trader["trades"], encoding="utf-8").read().splitlines()[1:] if os.path.exists(trader["trades"]) else []
    if lines:
        out += ["", "Last trades:", "", "| Time (UTC) | Side | Coin | Price | $ | Why | P&L |",
                "| --- | --- | --- | --- | --- | --- | --- |"]
        for line in reversed(lines[-12:]):
            t, side, coin, price, _q, usd, why, pnl, pct = line.split(",")
            out.append("| %s | %s | %s | %s | %s | %s | %s |" % (
                t, side, coin, price, usd, why, ("$%s (%s%%)" % (pnl, pct)) if pnl else ""))
    return out + [""]


def page(books, px, now):
    out = ["# Crypto traders", "",
           "Paper money, $%s per trader. Updated %s UTC. Prices: Coinbase, live. Each trader is compared with "
           "just holding coins over its own dates." % (format(START_CASH, ",.0f"), stamp(now)), ""]
    for trader, ledger in books:
        out += section(trader, ledger, px)
    out += ["Rules are in `engine/crypto.py`. Most people who day-trade meme coins lose money; "
            "this page shows whether these rulebooks do too."]
    with open(PAGE, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    now = time.time()
    prods = products()
    px = {pid: _f(p, "price") for pid, p in prods.items()}
    print("Crypto check %s UTC, %d coins listed" % (stamp(now), len(prods)))
    books, seen = [], {}
    for trader in TRADERS:
        path = trader["ledger"]
        ledger = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else new_ledger(px, trader["kind"])
        print("%s: %d holding" % (trader["label"], len(ledger["positions"])))
        if trader["kind"] == "trend":
            trend_step(ledger, px, now, a.dry, print, trader["trades"])
        else:
            check_exits(ledger, px, now, a.dry, print, trader["trades"])
            check_entries(ledger, prods, px, now, a.dry, print, trader["trades"], trader["alive_only"], seen)
        ledger["cooldown"] = {c: t for c, t in ledger["cooldown"].items() if t > now}
        books.append((trader, ledger))
        if a.dry:
            continue
        os.makedirs(STATE_DIR, exist_ok=True)
        peaks = {c: p.pop("peak", None) for c, p in ledger["positions"].items()}   # peaks are recomputed every run
        json.dump(ledger, open(path, "w", encoding="utf-8"), indent=1)
        for c, pk in peaks.items():
            if pk is not None:
                ledger["positions"][c]["peak"] = pk
        for name, val in scores(trader, ledger, px):
            print("  %-40s $%s  %+.2f%%" % (name[:40], format(val, ",.2f"), (val / START_CASH - 1) * 100))
    if not a.dry:
        page(books, px, now)


if __name__ == "__main__":
    main()
