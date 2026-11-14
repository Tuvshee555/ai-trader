"""The scoreboard: the engine's book against the same money left in SPY.

    python engine/score.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import DATA, PAPER, STATE_DIR, call, latest_prices  # noqa: E402


def main():
    path = os.path.join(STATE_DIR, "state.json")
    if not os.path.exists(path):
        sys.exit("The engine has not run yet.")
    start = json.load(open(path, encoding="utf-8"))["start"]
    s, acct = call("GET", PAPER + "/v2/account")
    s, t = call("GET", DATA + "/v2/stocks/trades/latest?feed=iex&symbols=SPY")
    spy = float(t["trades"]["SPY"]["p"])
    book = start["budget"] + float(acct["equity"]) - start["account_equity"]
    bench = start["budget"] * spy / start["spy_prev_close"]
    print("Started %s with $%s (paper)." % (start["session"], format(start["budget"], ",.0f")))
    print("  Engine book now:      $%s  (%+.2f%%)" % (format(book, ",.2f"), (book / start["budget"] - 1) * 100))
    print("  Same money in SPY:    $%s  (%+.2f%%)" % (format(bench, ",.2f"), (bench / start["budget"] - 1) * 100))
    print("  Ahead of SPY by:      $%s" % format(book - bench, ",.2f"))
    s, pos = call("GET", PAPER + "/v2/positions")
    for p in sorted(pos, key=lambda p: -float(p["market_value"])):
        print("    %-6s $%10s  %+7.2f%%" % (p["symbol"], format(float(p["market_value"]), ",.2f"),
                                          float(p["unrealized_plpc"]) * 100))

    import books
    doc = books._read(books.BOOKS, {"books": {}})
    syms = sorted({s_ for b in doc["books"].values() for s_ in b["shares"]} | {books.BENCH})
    engine = {"value": book, "start_value": start["budget"],
              "spy_start": doc.get("engine_spy_open") or start["spy_prev_close"], "start_session": start["session"]}
    print("\nTournament (best vs SPY first):")
    books.show(books.table(doc["books"], latest_prices(syms), engine))
    picks = books._read(os.path.join(STATE_DIR, "ai_picks.json"), None)
    if picks:
        print("\nLatest AI picks (%s session): %s" % (picks["session"], picks["view"]))
        print("  " + ", ".join("%s %.0f%%" % (p["symbol"], p["weight"] * 100) for p in picks["picks"]))


if __name__ == "__main__":
    main()
