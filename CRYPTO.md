# Crypto traders

Paper money, $10,000 per trader. Updated 2026-11-19 21:07 UTC. Prices: Coinbase, live. Each trader is compared with just holding coins over its own dates.

## Pump chaser, any coin

Started 2026-11-14 07:20 UTC with $10,000. Buys any coin that pumps, even one that was dead before.

| Player | Value | Return |
| --- | --- | --- |
| Just hold Bitcoin | $9,240.17 | **-7.60%** |
| Pump chaser, any coin | $9,124.87 | **-8.75%** |
| Just hold 4 alive meme coins (DOGE, PEPE, TRUMP, FARTCOIN) | $8,801.44 | **-11.99%** |

Closed trades: 14, winners: 4 (29%). Fees and spread paid: $275.88.

Holding now:

| Coin | Bought (UTC) | Entry | Now | P&L | Sells below | Sells by |
| --- | --- | --- | --- | --- | --- | --- |
| USELESS-USD | 2026-11-19 07:07 | 0.10548 | 0.09844 | -7.6% | 0.095895 | 2026-11-20 07:07 |
| RAVE-USD | 2026-11-19 17:07 | 0.1168 | 0.1234 | +4.6% | 0.11709 | 2026-11-20 17:07 |

Last trades:

| Time (UTC) | Side | Coin | Price | $ | Why | P&L |
| --- | --- | --- | --- | --- | --- | --- |
| 2026-11-19 20:45 | sell | SYRUP-USD | 0.09684 | 1668.81 | trailing stop | $-204.06 (-10.90%) |
| 2026-11-19 17:07 | buy | RAVE-USD | 0.1168 | 1812.01 | pump +13.0% |  |
| 2026-11-19 15:07 | buy | SYRUP-USD | 0.1076 | 1872.86 | pump +10.9% |  |
| 2026-11-19 11:35 | sell | ICNT-USD | 0.39204 | 2144.49 | trailing stop | $349.95 (19.50%) |
| 2026-11-19 07:07 | buy | USELESS-USD | 0.10548 | 1822.57 | pump +10.5% |  |
| 2026-11-19 04:10 | sell | SENT-USD | 0.023076 | 1834.57 | trailing stop | $39.06 (2.18%) |
| 2026-11-19 03:07 | buy | SENT-USD | 0.02236 | 1795.52 | pump +19.4% |  |
| 2026-11-19 02:20 | sell | PROS-USD | 0.64206 | 1674.74 | trailing stop | $-130.49 (-7.23%) |
| 2026-11-19 01:55 | sell | IRYS-USD | 0.023463 | 1922.77 | trailing stop | $110.88 (6.12%) |
| 2026-11-19 01:07 | buy | IRYS-USD | 0.02189 | 1811.90 | pump +49.5% |  |
| 2026-11-19 00:07 | sell | RENDER-USD | 1.3864 | 1691.18 | 24 hours up | $-140.45 (-7.67%) |
| 2026-11-18 20:07 | buy | PROS-USD | 0.6852 | 1805.23 | pump +36.9% |  |

## Pump chaser, alive coins only

Started 2026-11-18 10:07 UTC with $10,000. Buys a pump only if the coin traded at least $1M a day on average in the week before it.

| Player | Value | Return |
| --- | --- | --- |
| Pump chaser, alive coins only | $10,039.01 | **+0.39%** |
| Just hold 5 alive meme coins (DOGE, PEPE, TRUMP, PENGU, FARTCOIN) | $9,683.20 | **-3.17%** |
| Just hold Bitcoin | $9,593.75 | **-4.06%** |

Closed trades: 1, winners: 1 (100%). Fees and spread paid: $31.06.

Holding now:

| Coin | Bought (UTC) | Entry | Now | P&L | Sells below | Sells by |
| --- | --- | --- | --- | --- | --- | --- |
| USELESS-USD | 2026-11-19 07:07 | 0.10548 | 0.09844 | -7.6% | 0.095895 | 2026-11-20 07:07 |

Last trades:

| Time (UTC) | Side | Coin | Price | $ | Why | P&L |
| --- | --- | --- | --- | --- | --- | --- |
| 2026-11-19 07:07 | buy | USELESS-USD | 0.10548 | 2036.88 | pump +10.5% |  |
| 2026-11-18 17:05 | sell | PEARL-USD | 2.08656 | 2184.41 | trailing stop | $184.41 (9.22%) |
| 2026-11-18 15:07 | buy | PEARL-USD | 1.8914 | 2000.00 | pump +8.0% |  |

## Trend: Bitcoin + Ethereum

Started 2026-11-19 07:44 UTC with $10,000. Holds Bitcoin and Ethereum, at most half the book each: a quarter of that half for every one of the coin's 20, 50, 100 and 200-day averages it closed above yesterday, cash for the rest.

| Player | Value | Return |
| --- | --- | --- |
| Trend: Bitcoin + Ethereum | $10,000.00 | **+0.00%** |
| Just hold half Bitcoin, half Ethereum | $9,745.11 | **-2.55%** |
| Just hold Bitcoin | $9,742.34 | **-2.58%** |

Closed trades: 0, winners: 0 (n/a). Fees and spread paid: $0.00.

Holding now:

| Coin | Share of book | Target | Value | P&L |
| --- | --- | --- | --- | --- |
| BTC-USD | 0% | 0.0% | $0.00 |  |
| ETH-USD | 0% | 0.0% | $0.00 |  |
| cash | 100% | | $10,000.00 | |

Rules are in `engine/crypto.py`. Most people who day-trade meme coins lose money; this page shows whether these rulebooks do too.
