# Crypto Cut stop-rule replay — pre-registered 2026-10-28 before any result was seen

Question: does a different stop rule turn two-detector setups into cards with positive expectancy?
Rules held fixed: detectors, confluence=2, liquidity $2M, target = highest high in 120d above entry+risk, RR>=2,
10-day time stop, 7-day cooldown, max 5 cards/day, ambiguous days dropped.

Variants (only these three, no tuning after):
  A  current: stop = 10-day low; risk >= 1 ATR14; stop <= 15%
  B  ATR stop: stop = entry - 2*ATR14; stop <= 25%
  C  wide low: stop = 10-day low; risk >= 1 ATR14; stop <= 25%

Costs: 0.2% round trip deducted from every trade (in R units).
Adopt a variant only if ALL hold:
  1. n >= 30 resolved trades
  2. avg R > 0 after costs
  3. bootstrap 95% lower bound of avg R > -0.10
  4. it is not worse than A on avg R (if A has n>=10)
Otherwise: no change, and report that.
Known bias: universe is today's frozen top-50, so it favours coins that survived.
