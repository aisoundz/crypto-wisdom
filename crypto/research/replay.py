import json, sys, os, time, statistics, random, datetime as dt, urllib.request
CW = sys.argv[1]; CACHE = "candles"; os.makedirs(CACHE, exist_ok=True)
CFG = json.load(open(os.path.join(CW, "crypto/config.json"))); g = CFG["gates"]; det = CFG["detectors"]
UTC = dt.timezone.utc
def fetch(sym):
    p = f"{CACHE}/{sym}.json"
    if os.path.exists(p): return json.load(open(p))
    rows = []; end = dt.datetime(2026, 10, 28, tzinfo=UTC)
    for _ in range(3):  # 3 x 300 days
        start = end - dt.timedelta(days=300)
        url = f"https://api.exchange.coinbase.com/products/{sym}-USD/candles?granularity=86400&start={start.isoformat()}&end={end.isoformat()}"
        for a in range(4):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "crypto-cut-replay/1.0"}), timeout=20) as r:
                    got = json.load(r); break
            except Exception as e:
                got = None; time.sleep(2 * (a + 1))
        if not got: break
        rows += got; end = start; time.sleep(0.35)
    seen = {}; [seen.__setitem__(r[0], r) for r in rows]
    rows = sorted(seen.values(), key=lambda r: r[0])
    out = [{"date": dt.datetime.fromtimestamp(r[0], UTC).date().isoformat(), "low": r[1], "high": r[2], "open": r[3], "close": r[4], "dvol": r[5] * r[4]} for r in rows]
    json.dump(out, open(p, "w")); return out
def atr(c, n):
    return sum(max(c[i]["high"]-c[i]["low"], abs(c[i]["high"]-c[i-1]["close"]), abs(c[i]["low"]-c[i-1]["close"])) for i in range(len(c)-n, len(c))) / n
def ret(c, d): return (c[-1]["close"] / c[-1-d]["close"] - 1) * 100
data = {s: fetch(s) for s in CFG["universe"]}
dates = sorted({x["date"] for x in data["BTC"]})
idx = {s: {x["date"]: i for i, x in enumerate(c)} for s, c in data.items()}
need = 122
def stop_for(v, c, entry, a14):
    if v == "B": s = entry - 2 * a14; return s, (entry - s) / entry * 100 <= 25
    s = min(x["low"] for x in c[-g["stop_lookback_days"]:]); risk = entry - s
    return s, risk >= a14 and risk > 0 and risk / entry * 100 <= (15 if v == "A" else 25)
def resolve(full, i0, entry, stop, target):
    risk = entry - stop
    for k, d in enumerate(full[i0+1:i0+1+CFG["time_stop_days"]], 1):
        hs, ht = d["low"] <= stop, d["high"] >= target
        if hs and ht: return "amb", None
        if hs: return "stop", -1.0
        if ht: return "target", (target - entry) / risk
        if k == CFG["time_stop_days"]: return "time", (d["close"] - entry) / risk
    return "open", None
res = {}
for v in "ABC":
    trades, last_pub, fired2 = [], {}, 0
    for day in dates:
        bi = idx["BTC"].get(day)
        if bi is None or bi < need: continue
        btc7 = ret(data["BTC"][:bi+1], 7); cands = []
        for s, full in data.items():
            i = idx[s].get(day)
            if i is None or i < need: continue
            c = full[:i+1]; last, prior = c[-1], c[:-1]
            med = statistics.median(x["dvol"] for x in prior[-30:])
            hits = sum([last["dvol"] > 2 * med and last["close"] > last["open"],
                        last["close"] > max(x["high"] for x in prior[-20:]),
                        s != "BTC" and ret(c, 7) - btc7 >= 5])
            if hits < 2: continue
            fired2 += 1
            if last["dvol"] < g["min_daily_dollar_volume"]: continue
            entry = last["close"]; a14 = atr(c, 14); stop, ok = stop_for(v, c, entry, a14)
            if not ok: continue
            risk = entry - stop
            above = [x["high"] for x in prior[-120:] if x["high"] > entry + risk]
            if not above: continue
            tgt = max(above); rr = (tgt - entry) / risk
            if rr < 2: continue
            if s in last_pub and (dt.date.fromisoformat(day) - last_pub[s]).days < 7: continue
            cands.append((rr, s, i, entry, stop, tgt))
        for rr, s, i, entry, stop, tgt in sorted(cands, reverse=True)[:5]:
            last_pub[s] = dt.date.fromisoformat(day)
            st, r = resolve(data[s], i, entry, stop, tgt)
            cost = 0.002 * entry / (entry - stop)
            trades.append({"day": day, "sym": s, "status": st, "r": None if r is None else r - cost, "stop_pct": (entry-stop)/entry*100})
    done = [t["r"] for t in trades if t["r"] is not None]
    random.seed(7)
    boots = sorted(statistics.mean(random.choices(done, k=len(done))) for _ in range(5000)) if done else []
    res[v] = {"two_detector_days": fired2, "cards": len(trades), "resolved": len(done),
              "ambiguous": sum(t["status"] == "amb" for t in trades),
              "avg_r": round(statistics.mean(done), 3) if done else None,
              "ci95": [round(boots[125], 3), round(boots[4875], 3)] if boots else None,
              "win_rate": round(sum(r > 0 for r in done) / len(done), 2) if done else None,
              "median_stop_pct": round(statistics.median(t["stop_pct"] for t in trades), 1) if trades else None,
              "cards_per_month": round(len(trades) / (len([d for d in dates if idx['BTC'][d] >= need]) / 30), 1)}
    json.dump(trades, open(f"trades_{v}.json", "w"), indent=0)
print("days tested:", len([d for d in dates if idx["BTC"][d] >= need]), dates[need], "→", dates[-1])
print(json.dumps(res, indent=1))
