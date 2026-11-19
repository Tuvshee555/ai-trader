# AI trader (paper money)

An experiment: can a rules-based engine beat simply holding the S&P 500? It trades **fake money** on an Alpaca paper account. Nothing here can reach a live account: the trading URL is hard-coded to Alpaca's paper endpoint.

**The live score is in [SCOREBOARD.md](SCOREBOARD.md)**, updated after every market day. The crypto traders are on **[CRYPTO.md](CRYPTO.md)**.

## Crypto traders

`engine/crypto.py` runs every hour in the cloud (`.github/workflows/crypto.yml`), all week. It is a $10,000 paper ledger priced from Coinbase's free live data, and it does not touch the Alpaca account. It scans every USD coin with at least $1M traded in 24 hours and buys the ones pumping: up 8% or more in 24 hours, breaking above the last 6 hours' high on at least twice the usual volume. It holds up to 5 coins at 20% of the book each and sells 10% below the peak since buying, or after 24 hours. The stop is checked on 5-minute prices, like a stop order resting at the exchange. Until 2026-11-16 it used hourly prices and skipped the hour of the buy. That recorded ASTER at -22.8% instead of -8.2%, so the first three trades were re-checked on 5-minute prices and the ledger was corrected (+$283). Every buy and sell pays 0.5% for fees and spread. It is compared with just holding Bitcoin and just holding the meme coins that were alive (at least $1M a day on average in the week before the start; on 2026-11-14 that was DOGE, PEPE, TRUMP and FARTCOIN) over the same dates. Until 2026-11-18 the basket held 14 meme coins, and on Coinbase most of them were dead, trading as little as $50k a day. A second trader with the same rules started on 2026-11-18. It buys a pump only if the coin traded at least $1M a day on average in the week before it, because the first trader kept buying dead coins' one-off pumps: RARE traded $70k a day before its +74% pump. The rules were fixed before the first run.

A replay on Coinbase hourly prices for all 398 USD coins, 2026-05-31 to 2026-11-18, says pump chasing is a losing idea, not a badly tuned one. The replay bought the same coins at the same hours as the live trader did over 11-14 to 11-18 and ended within $20 of it. Over the whole 171 days the first trader would have lost 97.5% (808 trades, 31% winners, an average trade -2.3%) and the alive-only one 91.2%. Six other settings (20% trail, 20% trail with a 72-hour hold, 5% trail, 6-hour hold, +4% or +20% pumps) all lost 91% to 98%, and requiring $5M a day of past trading still lost 56.5%. Holding Bitcoin lost 13%. Both traders keep running to the verdict as agreed, so the live record can confirm it. Buying winners or losers of the week lost too (-24% to -85%). Buying alive coins after a 15% fall made +8.1% with one setting, but 11 of its 12 neighbouring settings lost money, so that was luck and it was not added.

A third trader, **Trend: Bitcoin + Ethereum** (added 2026-11-18), is not a day trader. Each coin gets at most half the book: a quarter of that half for every one of its 20, 50, 100 and 200-day averages it closed above on the last finished UTC day, cash for the rest. On Coinbase daily prices from mid-2018 to 2026-11, with the same 0.5% cost, it made 34% a year with a worst drop of -53%, against 29% a year and -77% for holding Bitcoin; in 2022 it lost 33% while Bitcoin lost 64%. All four averages are used because any single one is a lucky pick: Bitcoin above its 20-day average alone made 6% a year, above its 50-day 42%. It is compared with holding Bitcoin and holding half Bitcoin, half Ethereum.

## What runs

`engine/` is the trader. It runs in the cloud on GitHub Actions (`.github/workflows/daily.yml`), so no computer has to be on. Every market day at 22:45 Ulaanbaatar time (14:45 UTC, with a backup run at 18:00 UTC; it only runs while the market is open, so every player trades at live session prices) it runs `engine/run.py` and commits the state in `trader/engine/` and the scoreboard back to this repo. The keys are GitHub Actions secrets. The runs are started on time by a small Vercel cron project ([clock/](clock/README.md)), because GitHub's own schedule fires late or not at all (3 of about 20 hourly slots on 2026-11-14); GitHub's schedule stays as a backup. Each run:

1. Downloads daily prices for about 100 of the largest US companies.
2. Four signals each rank every stock, and the votes are combined into one score:
   - **momentum** (40%): what has gone up over the last 6 to 12 months
   - **low volatility** (25%): steadier stocks
   - **trend** (20%): price above its 200-day average
   - **reversal** (15%): a small dip in the last week
3. It holds the top 10, gives steadier stocks more money, and caps any stock at 15%.
4. If the whole market is below its 200-day average, it only invests half.
5. Every order goes through the risk check from the trader-skill pack before it is sent.
6. It rebalances once a week (every 5 trading days) and logs the score every day.

The book is $40,000 of the paper account (`trader/config.json`).

## The tournament

The engine competes with other players, each with its own $40,000, on one scoreboard:

| Player | What it does | Trades |
| --- | --- | --- |
| Engine | the four signals vote (above) | weekly, real paper orders |
| Momentum only | the backtest's best single signal | weekly |
| Copy Berkshire 13F | Berkshire Hathaway's top 5 (`trader/targets.json`) | when a new filing replaces the file |
| AI judgement | Claude reads prices and headlines and picks 5 to 15 stocks (`engine/ai_pick.py`) | weekly |
| All 100 equally | the fair bar | monthly |
| Momentum top 3 (bold) | only the 3 strongest stocks by momentum, equally | weekly |
| 3x Nasdaq in uptrends (bold) | TQQQ while QQQ is above its 200-day average, T-bills (BIL) below it | checked daily |

The two bold players were added on 2026-11-18 to go for more money. In the backtest (2017 to 2026) top-3 momentum made 44.7% a year with a worst drop of -40%. Most of that is hindsight: with NVDA, TSLA, PLTR, AMD, AVGO and NFLX taken out of the list it made 17.4% a year, against 14.8% for holding the rest equally. TQQQ-in-uptrends made 32.8% a year with a worst drop of -59%, against 19.6% and -35% for holding QQQ; the Nasdaq was itself the decade's winner, which flatters it. Momentum top 3 started at the engine's first open like the other mechanical players. The TQQQ player started at its first live run (2026-11-18), because QQQ crossed its 200-day average on 2026-11-13 and a filled-at-the-first-open start could not replay that switch.

Every book is compared with SPY over its own dates. Only the engine sends orders to Alpaca. The others are shadow books in `trader/engine/books.json`, filled at the price when the daily run happens with the same 0.10% cost. The mechanical players started at the engine's first session, filled at that day's open. The AI player started at its first pick. The verdict is on 2026-12-14: the losers are dropped and the winner gets the money. One month is short, so a small lead then is mostly luck.

The AI player decides once a week. In the cloud it makes one OpenAI call (`gpt-5.5`, well under $1 a month). Run on a PC, `engine/ai_pick.py` uses the Claude Code CLI on the Claude subscription instead, with every tool switched off. The first pick (2026-11-16 session) was made that way. Its answer is checked before use (known symbols, at most 15% each, 5 to 15 stocks), and every prompt and answer is kept in `trader/engine/ai/`.

## Commands

```
python engine/score.py          # the scoreboard: every player vs the same money in SPY
python engine/ai_pick.py        # make the AI player's picks for the next session now
python engine/run.py --dry      # what it would do right now, places nothing
python engine/run.py --force    # rebalance now
python engine/backtest.py       # replay the strategy over 2017 to today
```

Logs are in `trader/engine/` (`history.csv` is the daily score, `log.jsonl` is every decision with the votes).

## What the backtest says

2017 to November 2026, with a 0.10% cost on every dollar traded and trades filled at the next day's open:

| | per year | worst drop |
| --- | --- | --- |
| The engine (all signals vote) | 17.8% | -28% |
| Holding all ~100 stocks equally | 17.0% | -34% |
| Holding SPY | 14.8% | -34% |

Read this honestly. The universe is today's biggest companies, which were chosen knowing they did well, so the fair comparison is the middle row. Against that, the engine's edge is under one point a year, which is too small to tell from luck. What it did do is lose less in bad years (2018 and 2022). It trailed SPY in 2019, 2023, 2025 and 2026.

No setting was tuned to improve these numbers.

## Keys

`.env.local` (not in git) holds the Alpaca **paper** key and secret. Never put live keys in it.

## The skill pack

`.claude/skills/` holds the 11 skills from [Jakeschincariol/trader-skill](https://github.com/Jakeschincariol/trader-skill) (MIT), usable in Claude Code as `/trader-copycat`, `/trader-news`, `/trader-pelosi` and so on. The engine uses its risk check. Pulling filings from the SEC needs a name and email in `trader/config.json` under `sec_user_agent`.
