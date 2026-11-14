"""Shared plumbing: keys, the Alpaca PAPER client and daily price bars.

The trading URL is hard-coded to the paper endpoint. Nothing in this engine can
reach a live account, whatever is in the env file.
"""
import datetime
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAPER = "https://paper-api.alpaca.markets"
DATA = "https://data.alpaca.markets"
STATE_DIR = os.path.join(ROOT, "trader", "engine")
CACHE_DIR = os.path.join(ROOT, "trader", "cache")


def env():
    out = {}
    path = os.path.join(ROOT, ".env.local")
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            m = re.match(r"\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$", line)
            if m:
                out[m.group(1)] = m.group(2)
    for k in ("ALPACA_API_KEY", "ALPACA_SECRET_KEY", "OPENAI_API_KEY"):
        out.setdefault(k, os.environ.get(k, ""))
    return out


_E = env()
_H = {"APCA-API-KEY-ID": _E["ALPACA_API_KEY"], "APCA-API-SECRET-KEY": _E["ALPACA_SECRET_KEY"],
      "Content-Type": "application/json"}


def call(method, url, body=None, tries=3):
    """Returns (status, parsed JSON or error text)."""
    data = json.dumps(body).encode() if body is not None else None
    for attempt in range(tries):
        req = urllib.request.Request(url, method=method, headers=_H, data=data)
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                text = r.read().decode()
                return r.status, (json.loads(text) if text else None)
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < tries - 1:
                time.sleep(3 + 3 * attempt)
                continue
            return e.code, e.read().decode()[:400]
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if attempt < tries - 1:
                time.sleep(2 + 2 * attempt)
                continue
            return 0, str(e)


def latest_prices(symbols, fallback=None):
    """Last trade prices (IEX, free and live), falling back to the given prices."""
    out = dict(fallback or {})
    for k in range(0, len(symbols), 50):
        s, b = call("GET", DATA + "/v2/stocks/trades/latest?feed=iex&symbols=" + ",".join(symbols[k:k + 50]))
        if s == 200:
            for sym, t in (b.get("trades") or {}).items():
                if t.get("p"):
                    out[sym] = float(t["p"])
    return out


def clock():
    """(session date, market open now?) from Alpaca's clock. The session is today's if
    the market is open, otherwise the next one."""
    s, c = call("GET", PAPER + "/v2/clock")
    if s != 200:
        raise RuntimeError("Alpaca clock call failed (%s): %s" % (s, c))
    return (c["timestamp"][:10] if c["is_open"] else c["next_open"][:10]), c


def fetch_bars(symbols, start="2016-01-01"):
    """Daily bars, split and dividend adjusted. {symbol: [[date, open, close], ...]}"""
    # The free plan only serves consolidated-tape data that is at least 15 minutes old.
    end = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=20))
    end = end.strftime("%Y-%m-%dT%H:%M:%SZ")
    out = {}
    for k in range(0, len(symbols), 40):
        chunk = symbols[k:k + 40]
        token = None
        while True:
            q = {"symbols": ",".join(chunk), "timeframe": "1Day", "start": start, "end": end,
                 "adjustment": "all", "feed": "sip", "limit": "10000"}
            if token:
                q["page_token"] = token
            s, b = call("GET", DATA + "/v2/stocks/bars?" + urllib.parse.urlencode(q))
            if s != 200:
                raise RuntimeError("bars request failed (%s): %s" % (s, b))
            for sym, rows in (b.get("bars") or {}).items():
                out.setdefault(sym, []).extend([r["t"][:10], r["o"], r["c"]] for r in rows)
            token = b.get("next_page_token")
            if not token:
                break
    return out


def load_bars(symbols, max_age_hours=6, refresh=False):
    """Bars from a local cache, refetched in full when stale (adjustments rewrite history)."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, "bars.json")
    if not refresh and os.path.exists(path):
        age = (time.time() - os.path.getmtime(path)) / 3600.0
        if age < max_age_hours:
            doc = json.load(open(path, encoding="utf-8"))
            if set(symbols) <= set(doc.get("asked", [])):
                return doc["bars"]
    bars = fetch_bars(symbols)
    json.dump({"asked": symbols, "bars": bars}, open(path, "w", encoding="utf-8"))
    return bars


def align(bars, bench, before=None):
    """Line every symbol up on the benchmark's trading days.

    Returns (dates, opens, closes) with None before a symbol's first bar and the
    last known close carried over any gap. `before` drops bars on or after that
    date, so a half-finished session never leaks into a signal.
    """
    dates = [r[0] for r in bars[bench] if before is None or r[0] < before]
    index = {d: i for i, d in enumerate(dates)}
    opens, closes = {}, {}
    for sym, rows in bars.items():
        o, c = [None] * len(dates), [None] * len(dates)
        for d, op, cl in rows:
            i = index.get(d)
            if i is not None:
                o[i], c[i] = op, cl
        last = None
        for i in range(len(dates)):
            if c[i] is None:
                c[i] = last
                o[i] = last
            else:
                last = c[i]
        opens[sym], closes[sym] = o, c
    return dates, opens, closes
