"""The tournament: other players run shadow books next to the engine.

    python engine/books.py          # the tournament table (same as score.py)

Only the engine sends orders to the paper account. Every other player is a
ledger kept in trader/engine/books.json, marked with the same live prices. A
decision fills at the price when the daily run happens (shortly after the open)
and pays the same 0.10% cost the backtest charges. The mechanical players start
at the engine's first session, filled at that day's open, so they start level.

Players besides the engine:
  momentum   the backtest's best single signal, rebalanced weekly
  copycat    Berkshire Hathaway's top 5 from its latest 13F (trader/targets.json),
             held until a newer filing replaces the file
  ai         Claude picks weekly from prices and headlines (ai_pick.py)
  equal      the fair bar: every stock in the universe equally, monthly

Each book is compared with SPY over its own dates. After about three months
the losers are dropped and the winner gets the money.
"""
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, STATE_DIR, align, latest_prices  # noqa: E402
from strategy import BENCH, UNIVERSE, features, targets  # noqa: E402

COST = 0.001
INVEST = 0.94          # same share of the book the engine invests
START_CASH = 40000.0
BOOKS = os.path.join(STATE_DIR, "books.json")
TOURNAMENT = os.path.join(STATE_DIR, "tournament.csv")
LOG = os.path.join(STATE_DIR, "log.jsonl")
VERDICT = "2026-12-14"   # one month after the start, as agreed on 2026-11-14

PLAYERS = {
    "momentum": {"label": "Momentum only", "every": 5, "backfill": True},
    "copycat": {"label": "Copy Berkshire 13F", "every": None, "backfill": True},
    "ai": {"label": "AI judgement (Claude)", "every": 5, "backfill": False},
    "equal": {"label": "All 100 equally (fair bar)", "every": 21, "backfill": True},
}


def _read(path, default):
    return json.load(open(path, encoding="utf-8")) if os.path.exists(path) else default


def _log(event, **kw):
    row = dict(at=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"), event=event, **kw)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def value(book, px):
    return book["cash"] + sum(n * px[s] for s, n in book["shares"].items())


def weights_of(book, px):
    v = value(book, px)
    return {s: n * px[s] / v for s, n in book["shares"].items()} if v > 0 else {}


def trade_to(book, weights, px):
    """Move the book to the target weights at these prices. Returns dollars traded."""
    eq = value(book, px)
    new, moved = {}, 0.0
    for s in set(book["shares"]) | set(weights):
        want = weights.get(s, 0.0) * eq * INVEST
        have = book["shares"].get(s, 0.0) * px[s]
        if want > 0 and have > 0 and abs(want - have) < max(0.005 * eq, 25):
            new[s] = book["shares"][s]          # too small to bother, like the engine
            continue
        moved += abs(want - have)
        if want > 0:
            new[s] = want / px[s]
    book["cash"] = eq - sum(n * px[s] for s, n in new.items()) - moved * COST
    book["shares"] = new
    return moved


def copycat_targets():
    doc = _read(os.path.join(ROOT, "trader", "targets.json"), {})
    w = {x["ticker"].upper().replace("-", "."): float(x["weight"]) for x in doc.get("weights", [])}
    total = sum(w.values())
    return ({k: v / total for k, v in w.items()} if total else {}), doc.get("filed") or doc.get("as_of")


def equal_targets(closes, i):
    names = [s for s in UNIVERSE if s in closes and features(closes[s], i)]
    return {s: 1.0 / len(names) for s in names}


def decide(name, book, closes, i, dates, session, allow_ai, px_now):
    """(weights, note) when the player wants to trade now, else (None, reason)."""
    every = PLAYERS[name]["every"]
    last = (book or {}).get("last_signal_date")
    due = book is None or (every and sum(1 for d in dates if d > last) >= every)
    if name == "copycat":
        w, filed = copycat_targets()
        if not w:
            return None, "no targets file"
        if book is not None and book.get("filed") == filed:
            return None, "holding until a newer 13F"
        return w, "13F filed %s" % filed
    if not due:
        return None, "not due"
    held = list((book or {}).get("shares", {}))
    if name == "momentum":
        return targets(closes, i, held=[s for s in held if s in closes], weights={"momentum": 1.0})[0], "weekly"
    if name == "equal":
        return equal_targets(closes, i), "monthly"
    if name == "ai":
        import ai_pick
        cur = weights_of(book, px_now) if book else {}
        picks = ai_pick.get_or_make(session, dates[i], closes, i, cur, allow=allow_ai)
        if not picks:
            return None, "no AI picks for this session"
        return picks["weights"], "Claude: " + (picks.get("view") or "")[:120]
    return None, "unknown player"


def backfill(doc, bars, engine_start):
    """Start the mechanical players at the engine's first session, filled at that day's open."""
    if not engine_start:
        return
    dates_all, opens_all, _ = align(bars, BENCH)
    if engine_start not in dates_all:
        return
    k = dates_all.index(engine_start)
    dates, _o, closes = align(bars, BENCH, before=engine_start)
    i = len(dates) - 1
    opens = {s: opens_all[s][k] for s in opens_all if opens_all[s][k]}
    for name, p in PLAYERS.items():
        if not p["backfill"] or name in doc["books"]:
            continue
        w, note = decide(name, None, closes, i, dates, engine_start, False, opens)
        if not w or any(s not in opens for s in w):
            continue
        book = {"cash": START_CASH, "shares": {}, "start": {"session": engine_start, "value": START_CASH,
                                                             "spy": opens[BENCH]}}
        trade_to(book, w, opens)
        book["last_signal_date"] = dates[i]
        if name == "copycat":
            book["filed"] = copycat_targets()[1]
        doc["books"][name] = book
        _log("tournament_start", player=name, session=engine_start, filled_at="open", targets=w, note=note)
        print("  %s starts %s at that day's open" % (PLAYERS[name]["label"], engine_start))


def step(session, bars, dry=False, engine=None, allow_ai=True):
    os.makedirs(STATE_DIR, exist_ok=True)
    doc = _read(BOOKS, {"books": {}})
    if doc.get("last_session") == session and not dry:
        return
    backfill(doc, bars, (engine or {}).get("start_session"))
    dates, _o, closes = align(bars, BENCH, before=session)
    i = len(dates) - 1
    books = doc["books"]

    held = {BENCH}
    for b in books.values():
        held |= set(b["shares"])
    fallback = {s: closes[s][i] for s in closes if closes[s][i]}
    px = latest_prices(sorted(held | set(UNIVERSE)), fallback)

    print("Tournament, session %s:" % session)
    for name, p in PLAYERS.items():
        b = books.get(name)
        w, note = decide(name, b, closes, i, dates, session, allow_ai and not dry, px)
        if w is None:
            continue
        missing = [s for s in w if s not in px]
        if missing:
            print("  %-28s skipped, no price for %s" % (p["label"], " ".join(missing)))
            continue
        if dry:
            print("  %-28s would trade: %s" % (p["label"], note))
            continue
        if b is None:
            b = books[name] = {"cash": START_CASH, "shares": {},
                               "start": {"session": session, "value": START_CASH, "spy": px[BENCH]}}
        moved = trade_to(b, w, px)
        b["last_signal_date"] = dates[i]
        if name == "copycat":
            b["filed"] = copycat_targets()[1]
        _log("tournament_trade", player=name, session=session, targets=w, traded_usd=round(moved, 2), note=note)
        print("  %-28s traded $%s (%s)" % (p["label"], format(moved, ",.0f"), note))

    if dry:
        return
    rows = table(books, px, engine)
    new = not os.path.exists(TOURNAMENT)
    with open(TOURNAMENT, "a", encoding="utf-8") as fh:
        if new:
            fh.write("session,player,value_usd,return_pct,spy_same_dates_pct\n")
        for r in rows:
            fh.write("%s,%s,%.2f,%.3f,%.3f\n" % (session, r["key"], r["value"], r["ret"], r["spy"]))
    doc["last_session"] = session
    json.dump(doc, open(BOOKS, "w", encoding="utf-8"), indent=1)
    show(rows)
    scoreboard(rows, session)


def scoreboard(rows, session):
    """SCOREBOARD.md at the repo root: the page to open on a phone."""
    done = session >= VERDICT
    out = ["# Tournament scoreboard", "",
           "Paper money, $40,000 per player. Updated after the %s session (%s UTC)." % (
               session, datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")), "",
           ("**Verdict (%s): %s wins.** Losers get dropped; the winner gets the money." % (VERDICT, rows[0]["label"]))
           if done and rows else "Verdict on **%s**. Until then the leader can still change." % VERDICT, "",
           "| # | Player | Since | Value | Return | SPY same dates | vs SPY |",
           "| --- | --- | --- | --- | --- | --- | --- |"]
    for n, r in enumerate(rows, 1):
        out.append("| %d | %s | %s | $%s | %+.2f%% | %+.2f%% | **%+.2f** |" % (
            n, r["label"], r["since"], format(r["value"], ",.0f"), r["ret"], r["spy"], r["ret"] - r["spy"]))
    picks = _read(os.path.join(STATE_DIR, "ai_picks.json"), None)
    if picks:
        out += ["", "## Latest AI picks (%s session, %s)" % (picks["session"], picks.get("model", "")), "",
                picks.get("view", ""), "", "| Stock | Weight | Why |", "| --- | --- | --- |"]
        out += ["| %s | %.0f%% | %s |" % (p["symbol"], p["weight"] * 100, p["reason"].replace("|", "/"))
                for p in picks["picks"]]
        out.append("| cash | %.0f%% | |" % (picks.get("cash", 0) * 100))
    out += ["", "One month is mostly luck: a lead of a point or two proves nothing. See README.md for how it works."]
    with open(os.path.join(ROOT, "SCOREBOARD.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(out) + "\n")


def table(books, px, engine=None):
    rows = []
    if engine:
        rows.append({"key": "engine", "label": "Engine (4 signals vote)", "since": engine["start_session"],
                     "value": engine["value"], "ret": (engine["value"] / engine["start_value"] - 1) * 100,
                     "spy": (px[BENCH] / engine["spy_start"] - 1) * 100})
    for name, p in PLAYERS.items():
        b = books.get(name)
        if not b:
            continue
        v = value(b, px)
        rows.append({"key": name, "label": p["label"], "since": b["start"]["session"], "value": v,
                     "ret": (v / b["start"]["value"] - 1) * 100,
                     "spy": (px[BENCH] / b["start"]["spy"] - 1) * 100})
    return sorted(rows, key=lambda r: r["ret"] - r["spy"], reverse=True)


def show(rows):
    print("\n  %-28s %-11s %12s %8s %8s %8s" % ("player", "since", "value", "return", "SPY", "vs SPY"))
    for r in rows:
        print("  %-28s %-11s %12s %+7.2f%% %+7.2f%% %+7.2f" % (
            r["label"], r["since"], "$" + format(r["value"], ",.0f"), r["ret"], r["spy"], r["ret"] - r["spy"]))


if __name__ == "__main__":
    doc = _read(BOOKS, {"books": {}})
    syms = sorted({s for b in doc["books"].values() for s in b["shares"]} | {BENCH})
    show(table(doc["books"], latest_prices(syms)))
