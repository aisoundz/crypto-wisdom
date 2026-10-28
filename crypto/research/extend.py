import json, os, sys, time, datetime as dt, urllib.request
U = json.load(open(sys.argv[1]))["universe"]; UTC = dt.timezone.utc; FLOOR = dt.datetime(2019, 1, 1, tzinfo=UTC)
for s in U:
    p = f"candles/{s}.json"; c = json.load(open(p))
    end = dt.datetime.fromisoformat(c[0]["date"]).replace(tzinfo=UTC); rows = []
    while end > FLOOR:
        start = max(FLOOR, end - dt.timedelta(days=300)); got = None
        url = f"https://api.exchange.coinbase.com/products/{s}-USD/candles?granularity=86400&start={start.isoformat()}&end={end.isoformat()}"
        for a in range(4):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "crypto-cut-replay/1.0"}), timeout=20) as r:
                    got = json.load(r); break
            except Exception: time.sleep(2*(a+1))
        time.sleep(0.35)
        if not got: break
        rows += got; end = start
    old = [{"date": dt.datetime.fromtimestamp(r[0], UTC).date().isoformat(), "low": r[1], "high": r[2], "open": r[3], "close": r[4], "dvol": r[5]*r[4]} for r in rows]
    have = {x["date"] for x in c}
    merged = sorted([x for x in {x["date"]: x for x in old}.values() if x["date"] not in have] + c, key=lambda x: x["date"])
    json.dump(merged, open(p, "w")); print(s, merged[0]["date"], len(merged), flush=True)
