"""The daily run: decide, risk-check, place on the PAPER account, keep score.

    python engine/run.py            # the scheduled job
    python engine/run.py --dry      # show what it would do, place nothing
    python engine/run.py --force    # rebalance now even if it is not due

Runs once per market session. It rebalances every `rebalance_days` trading days
and only logs the score on the days in between. Orders sent before the open
wait in the queue and fill at the open.
"""
import argparse
import datetime
import importlib.util
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import PAPER, ROOT, STATE_DIR, align, call, latest_prices, load_bars  # noqa: E402
from strategy import BENCH, PARAMS, UNIVERSE, targets  # noqa: E402

STATE = os.path.join(STATE_DIR, "state.json")
LOG = os.path.join(STATE_DIR, "log.jsonl")
HISTORY = os.path.join(STATE_DIR, "history.csv")
INVEST = 0.94   # of the book; the config keeps a 5% cash buffer and this leaves room for rounding


def read(path, default):
    return json.load(open(path, encoding="utf-8")) if os.path.exists(path) else default


def log(event, **kw):
    os.makedirs(STATE_DIR, exist_ok=True)
    row = dict(at=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"), event=event, **kw)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")
    return row


def risk_checker():
    """The trader-skill pack's own risk check, used as the gate on every order."""
    path = os.path.join(ROOT, ".claude", "skills", "trader-risk", "check.py")
    spec = importlib.util.spec_from_file_location("trader_risk_check", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.check


def tournament(session, bars, dry, engine):
    """The other players. A failure here never stops the engine."""
    try:
        import books
        books.step(session, bars, dry=dry, engine=engine)
    except Exception as e:   # noqa: BLE001
        print("  tournament step failed: %s" % e)
        log("tournament_error", session=session, error=str(e)[:300])


def main():
    if sys.stdout is None:   # started windowless by the scheduler: keep the output in a file
        os.makedirs(STATE_DIR, exist_ok=True)
        sys.stdout = sys.stderr = open(os.path.join(STATE_DIR, "task.log"), "a", encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    cfg = read(os.path.join(ROOT, "trader", "config.json"), {})
    if not cfg.get("paper", True):
        sys.exit("config says paper is false. This engine only trades the paper account.")
    s, acct = call("GET", PAPER + "/v2/account")
    if s != 200:
        sys.exit("Alpaca account call failed (%s): %s" % (s, acct))
    if not str(acct.get("account_number", "")).startswith("PA"):
        sys.exit("not a paper account, stopping")
    s, clock = call("GET", PAPER + "/v2/clock")
    now = datetime.datetime.fromisoformat(clock["timestamp"][:19])
    nxt = datetime.datetime.fromisoformat(clock["next_open"][:19])
    session = clock["timestamp"][:10] if clock["is_open"] else clock["next_open"][:10]
    if not clock["is_open"] and (nxt - now).total_seconds() > 18 * 3600:
        print("Market is closed and the next open is more than 18 hours away. Nothing to do.")
        return

    state = read(STATE, {})
    if state.get("last_session") == session and not (a.force or a.dry):
        print("Already ran for the %s session." % session)
        if state.get("start"):   # the tournament retries on its own if it failed last time
            tournament(session, load_bars(UNIVERSE + [BENCH]), False, engine_score(state, acct))
        return

    bars = load_bars(UNIVERSE + [BENCH])
    dates, _opens, closes = align(bars, BENCH, before=session)
    i = len(dates) - 1
    equity = float(acct["equity"])
    budget = float(cfg.get("budget") or 0)
    if not state.get("start"):
        state["start"] = {"session": session, "account_equity": equity, "budget": budget,
                          "spy_prev_close": closes[BENCH][i]}
    book = state["start"]["budget"] + (equity - state["start"]["account_equity"])

    s, positions = call("GET", PAPER + "/v2/positions")
    held = {p["symbol"]: float(p["qty"]) for p in positions}
    done = [d for d in dates if d > state.get("last_signal_date", "")] if state.get("last_signal_date") else None
    due = a.force or done is None or len(done) >= PARAMS["rebalance_days"]
    print("Session %s | signal uses closes to %s | account $%s | book $%s | %s" % (
        session, dates[i], format(equity, ",.2f"), format(book, ",.2f"),
        "REBALANCE" if due else "no rebalance due (%d of %d days)" % (len(done), PARAMS["rebalance_days"])))

    placed = []
    if due:
        want, info = targets(closes, i, held=[s_ for s_ in held if s_ in closes])
        symbols = sorted(set(want) | set(held))
        px = latest_prices(symbols, {s_: closes[s_][i] for s_ in symbols if s_ in closes and closes[s_][i]})
        sells, buys = [], []
        for sym in symbols:
            if sym not in px:
                print("  no price for %s, leaving it alone" % sym)
                continue
            tgt = want.get(sym, 0.0) * book * INVEST
            cur = held.get(sym, 0.0) * px[sym]
            diff = tgt - cur
            base = {"symbol": sym, "type": "market", "time_in_force": "day"}
            if tgt == 0 and cur > 0:
                sells.append(dict(base, side="sell", qty=("%.9f" % held[sym]).rstrip("0").rstrip(".")))
            elif abs(diff) < max(0.005 * book, 25):
                continue
            elif diff > 0:
                buys.append(dict(base, side="buy", notional="%.2f" % diff))
            else:
                qty = min(held[sym], -diff / px[sym])
                sells.append(dict(base, side="sell", qty=("%.4f" % qty)))
        orders = sells + buys

        cash = book - sum(held[s_] * px[s_] for s_ in held if s_ in px)
        portfolio = {"cash": round(cash, 2), "positions": [{"symbol": s_, "qty": q} for s_, q in held.items()]}
        verdict = risk_checker()(orders, cfg, portfolio, px, None, None)
        print("  market %s, invested share %.0f%%" % ("above its 200-day average" if info["risk_on"]
              else "BELOW its 200-day average (half invested)", info["exposure"] * 100))
        for o, r in zip(orders, verdict["results"]):
            amount = ("$" + o["notional"]) if "notional" in o else (o["qty"] + " sh")
            print("  %-5s %-4s %-6s %10s  %s" % (r["verdict"], o["side"], o["symbol"], amount,
                                              "; ".join(r["reasons"])))
        if not a.dry:
            s, open_orders = call("GET", PAPER + "/v2/orders?status=open&limit=200")
            for o in open_orders or []:
                call("DELETE", PAPER + "/v2/orders/" + o["id"])
            if open_orders:
                print("  cancelled %d older open order(s)" % len(open_orders))
            for o, r in zip(orders, verdict["results"]):
                if r["verdict"] != "PASS":
                    continue
                body = dict(o, client_order_id="engine-%s-%s-%s" % (session.replace("-", ""), o["symbol"], o["side"]))
                s, resp = call("POST", PAPER + "/v2/orders", body)
                ok = s == 200 and isinstance(resp, dict)
                placed.append({"order": o, "ok": ok, "id": resp.get("id") if ok else None,
                               "error": None if ok else str(resp)[:200]})
                if not ok:
                    print("  FAILED %s %s: %s" % (o["side"], o["symbol"], str(resp)[:160]))
            state["last_signal_date"] = dates[i]
            log("rebalance", session=session, signal_date=dates[i], book=round(book, 2), targets=want,
                votes=info["votes"], risk_on=info["risk_on"], placed=placed,
                blocked=[r for r in verdict["results"] if r["verdict"] != "PASS"])
            print("  sent %d order(s), %d failed, %d blocked by the risk check" % (
                sum(p["ok"] for p in placed), sum(not p["ok"] for p in placed), verdict["block"]))

    if not a.dry:
        spy0 = state["start"]["spy_prev_close"]
        spy_now = latest_prices([BENCH], {BENCH: closes[BENCH][i]})[BENCH]
        bench = state["start"]["budget"] * spy_now / spy0
        new = not os.path.exists(HISTORY)
        with open(HISTORY, "a", encoding="utf-8") as fh:
            if new:
                fh.write("session,book_usd,spy_same_money_usd,account_equity\n")
            fh.write("%s,%.2f,%.2f,%.2f\n" % (session, book, bench, equity))
        state["last_session"] = session
        os.makedirs(STATE_DIR, exist_ok=True)
        json.dump(state, open(STATE, "w", encoding="utf-8"), indent=1)
        print("Score: book $%s vs same money in SPY $%s" % (format(book, ",.2f"), format(bench, ",.2f")))
    tournament(session, bars, a.dry, engine_score(state, acct))


def engine_score(state, acct):
    st = state["start"]
    return {"value": st["budget"] + float(acct["equity"]) - st["account_equity"], "start_value": st["budget"],
            "spy_start": st["spy_prev_close"], "start_session": st["session"]}


if __name__ == "__main__":
    main()
