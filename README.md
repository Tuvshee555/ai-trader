# AI trader (paper money)

An experiment: can a rules-based engine beat simply holding the S&P 500? It trades **fake money** on an Alpaca paper account. Nothing here can reach a live account: the trading URL is hard-coded to Alpaca's paper endpoint.

## What runs

`engine/` is the trader. Every market day at 22:45 (Ulaanbaatar time) a Windows scheduled task named `ai-trader-engine` runs `engine/run.py`:

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

## Commands

```
python engine/score.py          # the scoreboard: engine vs the same money in SPY
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
