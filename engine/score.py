"""The scoreboard: the engine's book against the same money left in SPY.

    python engine/score.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import DATA, PAPER, STATE_DIR, call  # noqa: E402


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


if __name__ == "__main__":
    main()
