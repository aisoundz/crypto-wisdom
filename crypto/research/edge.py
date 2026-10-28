import json, os, statistics, random, datetime as dt
U = json.load(open(os.environ["CFG"]))["universe"]
data = {s: json.load(open(f"candles/{s}.json")) for s in U}
idx = {s: {x["date"]: i for i, x in enumerate(c)} for s, c in data.items()}
dates = [x["date"] for x in data["BTC"]][:-1]  # drop today's incomplete candle
def sma(c, n): return sum(x["close"] for x in c[-n:]) / n
def atr(c, n): return sum(max(c[i]["high"]-c[i]["low"], abs(c[i]["high"]-c[i-1]["close"]), abs(c[i]["low"]-c[i-1]["close"])) for i in range(len(c)-n, len(c))) / n
def ret(c, d): return c[-1]["close"] / c[-1-d]["close"] - 1
def boot(xs, q=0.0085):
    random.seed(7); b = sorted(statistics.mean(random.choices(xs, k=len(xs))) for _ in range(5000))
    return round(b[int(q*5000)], 4), round(b[int((1-q)*5000)-1], 4)
def btc_up(day):
    i = idx["BTC"][day]; c = data["BTC"][:i+1]; return i >= 50 and c[-1]["close"] > sma(c, 50)
def resolve(full, i0, entry, stop, tgt):
    risk = entry - stop
    for k, d in enumerate(full[i0+1:i0+11], 1):
        if d["low"] <= stop and d["high"] >= tgt: return None
        if d["low"] <= stop: return -1.0
        if d["high"] >= tgt: return (tgt-entry)/risk
        if k == 10: return (d["close"]-entry)/risk
    return None
def summarize(name, trades):
    rs = [t[1] for t in trades]; mid = dates[len(dates)//2]
    h1 = [r for d, r in trades if d < mid]; h2 = [r for d, r in trades if d >= mid]
    lo, hi = boot(rs) if rs else (None, None)
    print(name, {"n": len(rs), "avg_R": round(statistics.mean(rs), 3) if rs else None, "CI98.3": [lo, hi],
                 "win": round(sum(r > 0 for r in rs)/len(rs), 2) if rs else None,
                 "half1": (len(h1), round(statistics.mean(h1), 3) if h1 else None),
                 "half2": (len(h2), round(statistics.mean(h2), 3) if h2 else None)})
# H1 = replay A trades filtered by BTC regime on entry day
A = json.load(open("trades_A.json"))
summarize("A (baseline)", [(t["day"], t["r"]) for t in A if t["r"] is not None])
summarize("H1 regime", [(t["day"], t["r"]) for t in A if t["r"] is not None and btc_up(t["day"])])
summarize("A in BTC downtrend", [(t["day"], t["r"]) for t in A if t["r"] is not None and not btc_up(t["day"])])
# H2
trades, last = [], {}
for day in dates:
    if idx["BTC"][day] < 100 or not btc_up(day): continue
    cands = []
    for s in U:
        i = idx[s].get(day)
        if i is None or i < 101: continue
        c = data[s][:i+1]
        if c[-1]["close"] <= sma(c, 100) or c[-1]["dvol"] * 0 + c[-1]["dvol"] < 2e6 * 0 + 2e6 and False: pass
        if c[-1]["close"] <= sma(c, 100) or c[-1]["dvol"] < 2e6: continue
        downs = sum(c[-1-k]["close"] < c[-2-k]["close"] for k in range(1, 5))
        if downs < 3 or c[-1]["close"] <= c[-2]["high"]: continue
        if s in last and (dt.date.fromisoformat(day) - last[s]).days < 7: continue
        entry = c[-1]["close"]; risk = 2*atr(c, 14)
        if risk/entry > 0.25: continue
        cands.append((c[-1]["dvol"], s, i, entry, entry-risk, entry+2*risk))
    for _, s, i, e, st, tg in sorted(cands, reverse=True)[:5]:
        last[s] = dt.date.fromisoformat(day); r = resolve(data[s], i, e, st, tg)
        if r is not None: trades.append((day, r - 0.002*e/(e-st)))
summarize("H2 pullback", trades)
# H3
mondays = [d for d in dates if dt.date.fromisoformat(d).weekday() == 0 and idx["BTC"][d] >= 120]
ex, strat, btc = [], [], []
for a, b in zip(mondays, mondays[1:]):
    bi, bj = idx["BTC"][a], idx["BTC"][b]; br = data["BTC"][bj]["close"]/data["BTC"][bi]["close"]-1
    r = 0.0
    if btc_up(a):
        rank = []
        for s in U:
            i, j = idx[s].get(a), idx[s].get(b)
            if i is None or j is None or i < 120 or data[s][i]["dvol"] < 2e6: continue
            rank.append((ret(data[s][:i+1], 28), s, i, j))
        top = sorted(rank, reverse=True)[:5]
        if top: r = statistics.mean(data[s][j]["close"]/data[s][i]["close"]-1 for _, s, i, j in top) - 0.002
    strat.append((a, r)); btc.append(br); ex.append((a, r - br))
def mdd(rs):
    eq, pk, dd = 1, 1, 0
    for r in rs: eq *= 1+r; pk = max(pk, eq); dd = min(dd, eq/pk-1)
    return round(dd*100, 1)
def total(rs):
    eq = 1
    for r in rs: eq *= 1+r
    return round((eq-1)*100, 1)
xs = [r for _, r in ex]; lo, hi = boot(xs); mid = len(xs)//2
print("H3 rotation", {"weeks": len(xs), "mean_weekly_excess_%": round(statistics.mean(xs)*100, 2), "CI98.3_%": [round(lo*100,2), round(hi*100,2)],
      "half1_%": round(statistics.mean(xs[:mid])*100, 2), "half2_%": round(statistics.mean(xs[mid:])*100, 2),
      "strat_total_%": total([r for _, r in strat]), "btc_total_%": total(btc),
      "strat_maxDD_%": mdd([r for _, r in strat]), "btc_maxDD_%": mdd(btc), "weeks_in_cash": sum(1 for a,_ in strat if not btc_up(a))})
print("period:", dates[100], "→", dates[-1])
