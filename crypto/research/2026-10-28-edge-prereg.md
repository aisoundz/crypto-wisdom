# Crypto edge search — pre-registered 2026-10-28 before any result was seen
Data: Coinbase daily candles, frozen top-50 universe, ~Sep 2024 → 27 Oct 2026. Costs 0.2% round trip on every trade.
Three hypotheses, no others, no parameter tuning after results:

H1 REGIME FILTER: current Crypto Cut rules (variant A), but only on days BTC closes above its 50-day average.
H2 PULLBACK IN UPTREND: coin close > its 100-day average AND BTC close > its 50-day average;
   coin fell >= 3 days of the last 4 and today closes above yesterday's high (the turn).
   Stop = entry - 2*ATR14, target = entry + 2*risk, 10-day time stop, 7-day cooldown, max 5/day.
H3 WEEKLY MOMENTUM ROTATION: every Monday close, if BTC > its 50-day average, hold equal-weight
   the top 5 coins by 28-day return (needs >=120 days history, >= $2M volume); else hold cash.
   Measured weekly vs BTC buy-and-hold over the same weeks.

PASS (each must hold; 3 tests → Bonferroni):
  H1/H2: n >= 30; avg R > 0 after costs; bootstrap 98.3% lower bound > 0; positive in BOTH halves of the period.
  H3: mean weekly excess return over BTC > 0 with 98.3% bootstrap lower bound > 0; positive in BOTH halves;
      max drawdown no worse than BTC's.
KILL: anything else. A kill is reported as a kill.
Known bias: today's top-50 universe favours coins that went on to succeed. This inflates H3 most.

## Addendum — written 2026-10-28 before the extended run
Extend history back to 2019-01-01 (or a coin's first Coinbase listing). Retest ONLY baseline A, H1 and H3, code unchanged
(H2 is dead and is not retested). Same pass bar, Bonferroni still /3. Additionally the segment before 2024-08-19
(data never seen in the first run) must be positive on its own. One run. Whatever it says is the answer.
