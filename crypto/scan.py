#!/usr/bin/env python3
"""The Crypto Cut: daily scan, journal, outcome resolution and edition build.

Reads daily candles from the Coinbase Exchange public API (no key), runs three
detectors over a frozen universe, applies the checks, resolves earlier cards,
and writes the day's edition files. Fails closed: if a publish gate fails,
crypto/out/GATE_FAILED is written and no edition is produced.

Usage:
  python crypto/scan.py                 # live data
  python crypto/scan.py --fixture F     # synthetic candles from a JSON file (tests)
  python crypto/scan.py --date YYYY-MM-DD   # override the edition date (tests)
"""
import argparse
import datetime as dt
import html
import json
import os
import statistics
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(ROOT, "config.json")))
DATA = os.path.join(ROOT, "data")
EDITIONS = os.path.join(ROOT, "editions")
OUT = os.path.join(ROOT, "out")
SITE = "https://" + CFG["site"]
UTC = dt.timezone.utc

CHECKS = [
    ("confluence", "Two detectors agree"),
    ("liquidity", "Enough volume to trade"),
    ("stop", "The stop can survive noise"),
    ("target", "The target is a level we found"),
    ("reward", "The reward covers the risk"),
    ("cooldown", "Not on cooldown"),
]
DETECTOR_NAMES = {
    "volume_expansion": "Volume expansion",
    "range_breakout": "Range breakout",
    "relative_strength": "Strength vs BTC",
}


# ---------- data ----------
def fetch_candles(sym):
    url = f"https://api.exchange.coinbase.com/products/{sym}-USD/candles?granularity=86400"
    last = None
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "crypto-cut/1.0"})
            with urllib.request.urlopen(req, timeout=20) as r:
                raw = json.load(r)
            return raw
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"{sym}: {last}")


def completed_daily(raw, today_utc):
    """Coinbase rows are [time, low, high, open, close, volume], newest first.
    Return completed UTC days only, oldest first, as dicts."""
    cutoff = dt.datetime.combine(today_utc, dt.time(0), tzinfo=UTC).timestamp()
    rows = [r for r in raw if r[0] < cutoff]
    rows.sort(key=lambda r: r[0])
    return [
        {"t": int(r[0]), "date": dt.datetime.fromtimestamp(r[0], UTC).date().isoformat(),
         "low": float(r[1]), "high": float(r[2]), "open": float(r[3]), "close": float(r[4]),
         "dvol": float(r[5]) * float(r[4])}
        for r in rows
    ]


# ---------- maths ----------
def atr(c, n):
    trs = []
    for i in range(len(c) - n, len(c)):
        prev = c[i - 1]["close"]
        trs.append(max(c[i]["high"] - c[i]["low"], abs(c[i]["high"] - prev), abs(c[i]["low"] - prev)))
    return sum(trs) / n


def ret(c, days):
    return (c[-1]["close"] / c[-1 - days]["close"] - 1) * 100


def fmt_price(p):
    if p >= 1000:
        return f"${p:,.0f}"
    if p >= 1:
        return f"${p:,.2f}"
    if p >= 0.01:
        return f"${p:.4f}"
    return f"${p:.8f}".rstrip("0")


# ---------- state ----------
def load_json(path, default):
    try:
        return json.load(open(path))
    except FileNotFoundError:
        return default


def save_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(obj, f, indent=1)


# ---------- outcomes ----------
def resolve(card, candles, time_stop):
    """Walk days after the card's close date. AMBIGUOUS when one day touched both."""
    after = [x for x in candles if x["date"] > card["close_date"]]
    entry, stop, target = card["entry"], card["stop"], card["target"]
    risk = entry - stop
    for i, d in enumerate(after, start=1):
        hit_stop, hit_tgt = d["low"] <= stop, d["high"] >= target
        if hit_stop and hit_tgt:
            return {"status": "ambiguous", "r": None, "resolved": d["date"]}
        if hit_stop:
            return {"status": "stop", "r": -1.0, "resolved": d["date"]}
        if hit_tgt:
            return {"status": "target", "r": round((target - entry) / risk, 2), "resolved": d["date"]}
        if i >= time_stop:
            return {"status": "time", "r": round((d["close"] - entry) / risk, 2), "resolved": d["date"]}
    return None


def record_stats(cards):
    def summary(rows):
        done = [r for r in rows if r.get("status") in ("stop", "target", "time")]
        n = len(done)
        avg = round(sum(r["r"] for r in done) / n, 2) if n else None
        return {"resolved": n, "avg_r": avg,
                "ambiguous": sum(1 for r in rows if r.get("status") == "ambiguous"),
                "open": sum(1 for r in rows if r.get("status") == "open")}
    return {"published": summary([c for c in cards if c["kind"] == "published"]),
            "cut": summary([c for c in cards if c["kind"] == "cut"]),
            "min_n_to_report": 30}


# ---------- main ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixture")
    ap.add_argument("--date")
    a = ap.parse_args()

    now = dt.datetime.now(UTC)
    today = dt.date.fromisoformat(a.date) if a.date else now.date()
    os.makedirs(OUT, exist_ok=True)
    gate_flag = os.path.join(OUT, "GATE_FAILED")
    if os.path.exists(gate_flag):
        os.remove(gate_flag)

    fixture = json.load(open(a.fixture)) if a.fixture else None
    g, det = CFG["gates"], CFG["detectors"]

    candles, errors = {}, {}
    for sym in CFG["universe"]:
        try:
            raw = fixture[sym] if fixture else fetch_candles(sym)
            candles[sym] = completed_daily(raw, today)
        except Exception as e:  # noqa: BLE001
            errors[sym] = str(e)[:120]
        if not fixture:
            time.sleep(0.2)

    need = max(det["volume_expansion"]["median_days"], g["target_lookback_days"], det["range_breakout"]["lookback_days"]) + 2
    usable = {s: c for s, c in candles.items() if len(c) >= need}
    for s in candles:
        if s not in usable:
            errors[s] = f"only {len(candles[s])} days of history"

    # ---- publish gates (fail closed) ----
    problems = []
    if len(usable) < CFG["publish_gates"]["min_scanned"]:
        problems.append(f"scanned {len(usable)} < {CFG['publish_gates']['min_scanned']}")
    if "BTC" not in usable:
        problems.append("BTC data missing")
    close_date = usable["BTC"][-1]["date"] if "BTC" in usable else None
    if close_date:
        close_end = dt.datetime.combine(dt.date.fromisoformat(close_date) + dt.timedelta(days=1), dt.time(0), tzinfo=UTC)
        ref_now = dt.datetime.combine(today, dt.time(12), tzinfo=UTC) if a.date else now
        age_h = (ref_now - close_end).total_seconds() / 3600
        if age_h > CFG["publish_gates"]["max_candle_age_hours"]:
            problems.append(f"newest close is {age_h:.1f}h old")
        stale = [s for s, c in usable.items() if c[-1]["date"] != close_date]
        for s in stale:
            errors[s] = f"last close {usable[s][-1]['date']}, expected {close_date}"
            usable.pop(s)
        if len(usable) < CFG["publish_gates"]["min_scanned"]:
            problems.append(f"only {len(usable)} coins have the {close_date} close")
    if problems:
        open(gate_flag, "w").write("\n".join(problems) + "\n")
        print("GATE FAILED:", "; ".join(problems))
        return 2

    edition_date = today.isoformat()
    cards_path = os.path.join(DATA, "cards.json")
    cards = load_json(cards_path, [])
    if any(c["edition_date"] == edition_date for c in cards):
        cards = [c for c in cards if c["edition_date"] != edition_date]  # rebuild of the same day

    # ---- resolve earlier cards ----
    for c in cards:
        if c.get("status") == "open" and c["symbol"] in candles:
            res = resolve(c, candles[c["symbol"]], CFG["time_stop_days"])
            if res:
                c.update(res)

    recent_pub = {c["symbol"] for c in cards if c["kind"] == "published" and
                  (today - dt.date.fromisoformat(c["edition_date"])).days < g["cooldown_days"]}

    btc7 = ret(usable["BTC"], det["relative_strength"]["days"])
    rows, fired, candidates = [], [], []
    for sym, c in usable.items():
        last = c[-1]
        prior = c[:-1]
        med = statistics.median(x["dvol"] for x in prior[-det["volume_expansion"]["median_days"]:])
        flags = {
            "volume_expansion": last["dvol"] > det["volume_expansion"]["vol_multiple"] * med and last["close"] > last["open"],
            "range_breakout": last["close"] > max(x["high"] for x in prior[-det["range_breakout"]["lookback_days"]:]),
            "relative_strength": sym != "BTC" and ret(c, det["relative_strength"]["days"]) - btc7 >= det["relative_strength"]["margin_pct"],
        }
        hits = [k for k, v in flags.items() if v]
        row = {"symbol": sym, "close": last["close"], "chg_1d": round(ret(c, 1), 2),
               "chg_7d": round(ret(c, 7), 2), "dvol": round(last["dvol"]), "detectors": hits,
               "result": "not fired", "failed": None, "reason": None}
        rows.append(row)
        if not hits:
            continue
        fired.append(row)

        entry = last["close"]
        a14 = atr(c, g["atr_days"])
        stop = min(x["low"] for x in c[-g["stop_lookback_days"]:])
        risk = entry - stop
        above = [x["high"] for x in prior[-g["target_lookback_days"]:] if x["high"] > entry + risk]
        target = max(above) if above else None
        rr = round((target - entry) / risk, 2) if target and risk > 0 else None
        stop_pct = risk / entry * 100 if risk > 0 else None
        plan = {"entry": entry, "stop": stop, "target": target, "rr": rr,
                "stop_pct": round(stop_pct, 2) if stop_pct else None, "atr": a14}

        checks = [
            ("confluence", len(hits) >= CFG["confluence_required"], "Single detector"),
            ("liquidity", last["dvol"] >= g["min_daily_dollar_volume"], "Thin volume"),
            ("stop", risk >= g["stop_min_atr"] * a14 and stop_pct is not None and stop_pct <= g["stop_max_pct"],
             "Stop inside daily noise" if risk < g["stop_min_atr"] * a14 else "Stop too far away"),
            ("target", target is not None, "No level above to aim at"),
            ("reward", rr is not None and rr >= g["min_reward_risk"], f"Reward under {g['min_reward_risk']:.0f}x risk"),
            ("cooldown", sym not in recent_pub, "Published in the last 7 days"),
        ]
        failed = next(((k, why) for k, ok, why in checks if not ok), None)
        row["plan"] = plan
        if failed:
            row.update(result="cut", failed=failed[0], reason=failed[1])
        else:
            row["result"] = "candidate"
            candidates.append(row)

    candidates.sort(key=lambda r: r["plan"]["rr"], reverse=True)
    published = candidates[:CFG["max_published_cards"]]
    for r in candidates[CFG["max_published_cards"]:]:
        r.update(result="cut", failed="capacity", reason="Over the daily card limit")
    for r in published:
        r["result"] = "published"

    # ---- cards ledger (published + cut-with-a-full-plan, for the comparison) ----
    for r in rows:
        p = r.get("plan")
        if not p or p["target"] is None or not p["stop_pct"]:
            continue
        if r["result"] != "published" and (r["result"] != "cut" or r["failed"] == "cooldown"):
            continue
        size = min(25.0, round(CFG["risk_per_card_pct"] / p["stop_pct"] * 100, 1))
        r["size_pct"] = size
        cards.append({"edition_date": edition_date, "close_date": close_date, "symbol": r["symbol"],
                      "kind": "published" if r["result"] == "published" else "cut",
                      "detectors": r["detectors"], "entry": p["entry"], "stop": p["stop"],
                      "target": p["target"], "rr": p["rr"], "size_pct": size, "status": "open"})
    save_json(cards_path, cards)

    # ---- journal: every coin, every day ----
    jpath = os.path.join(DATA, "journal.jsonl")
    lines = []
    if os.path.exists(jpath):
        lines = [l for l in open(jpath) if f'"edition_date": "{edition_date}"' not in l]
    for r in rows:
        lines.append(json.dumps({"edition_date": edition_date, "close_date": close_date, **{k: v for k, v in r.items() if k != "plan"},
                                 "plan": r.get("plan")}) + "\n")
    with open(jpath, "w") as f:
        f.writelines(lines)

    # ---- edition ----
    state = load_json(os.path.join(DATA, "state.json"), {})
    start = state.get("window_start") or edition_date
    state["window_start"] = start
    save_json(os.path.join(DATA, "state.json"), state)
    day_n = (today - dt.date.fromisoformat(start)).days + 1

    fell = {k: sum(1 for r in fired if r["failed"] == k) for k, _ in CHECKS}
    cut_list = sorted([r for r in fired if r["result"] == "cut"],
                      key=lambda r: (-len(r["detectors"]), -r["dvol"]))
    edition = {
        "edition": CFG["edition_name"], "edition_date": edition_date, "close_date": close_date,
        "day": day_n, "window_days": CFG["window_days"], "badge": "VALIDATION WINDOW · UNPROVEN",
        "counts": {"scanned": len(usable), "fired": len(fired), "cleared": len(published),
                   "cut": len(cut_list), "unavailable": len(errors)},
        "checks": [{"key": k, "label": lbl, "fell": fell.get(k, 0)} for k, lbl in CHECKS],
        "cards": [{"symbol": r["symbol"], "detectors": [DETECTOR_NAMES[d] for d in r["detectors"]],
                   "entry": r["plan"]["entry"], "stop": r["plan"]["stop"], "target": r["plan"]["target"],
                   "stop_pct": r["plan"]["stop_pct"], "rr": r["plan"]["rr"], "size_pct": r["size_pct"],
                   "time_stop_days": CFG["time_stop_days"],
                   "link": f"{SITE}/app/?signal={edition_date}-{r['symbol']}"} for r in published],
        "cut": [{"symbol": r["symbol"], "reason": r["reason"],
                 "detectors": [DETECTOR_NAMES[d] for d in r["detectors"]]} for r in cut_list],
        "market": {"btc_close": usable["BTC"][-1]["close"], "btc_7d": round(btc7, 2)},
        "record": record_stats(cards),
        "unavailable": errors,
        "generated_at": now.isoformat(timespec="seconds"),
        "card_image": f"{SITE}/crypto/editions/{edition_date}.png",
    }
    save_json(os.path.join(EDITIONS, f"{edition_date}.json"), edition)
    save_json(os.path.join(EDITIONS, "latest.json"), edition)
    idx = load_json(os.path.join(EDITIONS, "index.json"), [])
    idx = [e for e in idx if e["date"] != edition_date]
    idx.insert(0, {"date": edition_date, "day": day_n, "scanned": len(usable), "fired": len(fired), "cleared": len(published),
                   "symbols": [c["symbol"] for c in edition["cards"]]})
    idx.sort(key=lambda e: e["date"], reverse=True)
    save_json(os.path.join(EDITIONS, "index.json"), idx)

    open(os.path.join(OUT, "telegram.txt"), "w").write(telegram_text(edition))
    open(os.path.join(OUT, "caption.txt"), "w").write(caption_text(edition))
    open(os.path.join(OUT, "email.html"), "w").write(email_html(edition))
    open(os.path.join(OUT, "email.txt"), "w").write(email_text(edition))
    open(os.path.join(OUT, "edition_date"), "w").write(edition_date)
    print(f"{edition_date} day {day_n}: scanned {len(usable)}, fired {len(fired)}, cleared {len(published)}, unavailable {len(errors)}")
    return 0


# ---------- copy ----------
def pretty_date(d):
    return dt.date.fromisoformat(d).strftime("%a %d %b %Y")


def headline(e):
    n = e["counts"]["cleared"]
    if n == 0:
        return "NOTHING MADE THE CUT TODAY."
    return f"{'ONE' if n == 1 else str(n)} MADE THE CUT."


def record_line(e):
    p = e["record"]["published"]
    if p["resolved"] < e["record"]["min_n_to_report"]:
        return f"Not enough resolved cards yet to report a record ({p['resolved']} of {e['record']['min_n_to_report']})."
    c = e["record"]["cut"]
    cut = f"{c['avg_r']:+.2f}R" if c["avg_r"] is not None else "n/a"
    return f"Published cards average {p['avg_r']:+.2f}R over {p['resolved']} resolved, against {cut} for The Cut."


def caption_text(e):
    c = e["counts"]
    return (f"📊 <b>THE CRYPTO CUT</b>\n<i>{pretty_date(e['edition_date'])}</i>\n\n"
            f"🔍 Scanned <b>{c['scanned']}</b> → ⚡ Fired <b>{c['fired']}</b> → ✅ Qualified <b>{c['cleared']}</b>\n\n"
            f"Full note below. 🟡 Validation window, day {e['day']} of {e['window_days']}: unproven.")


def telegram_text(e):
    c = e["counts"]
    out = [f"📊 <b>THE CRYPTO CUT</b>", f"<i>{pretty_date(e['edition_date'])} · daily close {e['close_date']} UTC</i>", "",
           f"🔍 Scanned <b>{c['scanned']}</b> → ⚡ Fired <b>{c['fired']}</b> → ✅ Qualified <b>{c['cleared']}</b>", "",
           "<b>THE CHECKS, THIS MORNING</b>"]
    for ch in e["checks"]:
        out.append(f"× {ch['label']}: {ch['fell']} fell" if ch["fell"] else f"· {ch['label']}")
    out.append("")
    if e["cards"]:
        for k in e["cards"]:
            out += [f"🟢 <b>{k['symbol']}</b> · {', '.join(k['detectors'])}",
                    f"Entry {fmt_price(k['entry'])}",
                    f"🛑 Stop {fmt_price(k['stop'])} ({k['stop_pct']:.1f}% away)",
                    f"🎯 Target {fmt_price(k['target'])}",
                    f"⚖️ Reward {k['rr']:.1f}x risk · size {k['size_pct']:.1f}% of account",
                    f"⏳ Time stop {k['time_stop_days']} days",
                    f"<a href=\"{k['link']}\">Think it through in Crypto Wisdom</a>", ""]
    else:
        out += [f"😴 No cards today. Of the {c['fired']} that fired, none passed every check.", ""]
    if e["cut"]:
        out.append("✂️ <b>THE CUT: what we passed on</b>")
        for x in e["cut"][:8]:
            out.append(f"{x['symbol']}: {x['reason']}")
        if len(e["cut"]) > 8:
            out.append(f"+ {len(e['cut']) - 8} more on the site")
        out.append("")
    out += [f"📈 {record_line(e)}", "",
            f"🟡 Validation window, day {e['day']} of {e['window_days']}. Unproven. One identical note for every reader. "
            f"Not personal advice. Size is a share of your account at a fixed {CFG['risk_per_card_pct']}% risk.",
            f"{SITE}/"]
    return "\n".join(out)


def email_text(e):
    t = telegram_text(e)
    for tag in ("<b>", "</b>", "<i>", "</i>"):
        t = t.replace(tag, "")
    import re
    return re.sub(r'<a href="([^"]+)">([^<]+)</a>', r"\2: \1", t)


def email_html(e):
    esc = html.escape
    c = e["counts"]
    teal, red, ink, dim = "#00D4AA", "#E54B4B", "#111", "#666"
    checks = "".join(
        f'<tr><td style="padding:3px 0;font:14px Arial;color:{red if ch["fell"] else dim}">'
        f'{"×" if ch["fell"] else "·"} {esc(ch["label"])}{": " + str(ch["fell"]) + " fell" if ch["fell"] else ""}</td></tr>'
        for ch in e["checks"])
    cards = ""
    for k in e["cards"]:
        cards += (f'<table width="100%" style="border:1px solid #ddd;border-radius:8px;margin:0 0 12px"><tr><td style="padding:14px 16px;font:14px Arial;color:{ink}">'
                  f'<b style="font-size:18px">{esc(k["symbol"])}</b> <span style="color:{dim}">{esc(", ".join(k["detectors"]))}</span><br><br>'
                  f'Entry {fmt_price(k["entry"])}<br>'
                  f'<span style="color:{red}">Stop {fmt_price(k["stop"])}</span> ({k["stop_pct"]:.1f}% away)<br>'
                  f'Target {fmt_price(k["target"])}<br>'
                  f'Reward {k["rr"]:.1f}x risk · size {k["size_pct"]:.1f}% of account · time stop {k["time_stop_days"]} days<br><br>'
                  f'<a href="{k["link"]}" style="color:#0a8f74">Think it through in Crypto Wisdom</a></td></tr></table>')
    if not cards:
        cards = f'<p style="font:15px Arial;color:{ink}">No cards today. Of the {c["fired"]} that fired, none passed every check.</p>'
    cut = ", ".join(f'{esc(x["symbol"])} ({esc(x["reason"].lower())})' for x in e["cut"][:12]) or "Nothing fired today."
    addr = esc(os.environ.get("SIGNAL_POSTAL_ADDRESS", ""))
    return f"""<!doctype html><html><body style="margin:0;background:#f4f4f4">
<table width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:24px 12px">
<table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;background:#fff;border-radius:10px">
<tr><td style="padding:28px 32px 12px;border-bottom:2px solid #0b3d33">
<div style="font:bold 26px Arial;letter-spacing:6px;color:{ink}">CRYPTO WISDOM</div>
<div style="font:13px 'Courier New';letter-spacing:3px;color:{ink};margin-top:6px">THE CRYPTO CUT · {esc(pretty_date(e['edition_date']).upper())}</div></td></tr>
<tr><td style="padding:20px 32px"><img src="{e['card_image']}" width="536" alt="{esc(headline(e))} Scanned {c['scanned']}, fired {c['fired']}, cleared {c['cleared']}." style="width:100%;border-radius:12px;display:block"></td></tr>
<tr><td style="padding:0 32px 8px;font:15px Arial;color:{ink}"><b>Scanned {c['scanned']} → Fired {c['fired']} → Qualified {c['cleared']}</b><br>
<span style="color:{dim};font-size:13px">Daily close {e['close_date']} UTC</span></td></tr>
<tr><td style="padding:12px 32px"><div style="font:bold 13px Arial;letter-spacing:2px;color:{ink};margin-bottom:6px">THE CHECKS</div><table>{checks}</table></td></tr>
<tr><td style="padding:12px 32px">{cards}</td></tr>
<tr><td style="padding:4px 32px 12px;font:14px Arial;color:{ink}"><b>The Cut:</b> {cut}</td></tr>
<tr><td style="padding:4px 32px 16px;font:14px Arial;color:{ink}">{esc(record_line(e))}</td></tr>
<tr><td style="padding:16px 32px 28px;border-top:1px solid #eee;font:12px Arial;color:{dim};line-height:1.6">
Validation window, day {e['day']} of {e['window_days']}. Unproven. Every reader receives this identical note. It is general commentary, not personal advice, and crypto assets can lose most or all of their value.
Size is shown as a share of your account at a fixed {CFG['risk_per_card_pct']}% risk.<br>
<a href="{SITE}/" style="color:#0a8f74">{CFG['site']}</a> · {addr}<br>
<a href="{{{{{{RESEND_UNSUBSCRIBE_URL}}}}}}" style="color:{dim}">Unsubscribe</a></td></tr>
</table></td></tr></table></body></html>"""


if __name__ == "__main__":
    sys.exit(main())
