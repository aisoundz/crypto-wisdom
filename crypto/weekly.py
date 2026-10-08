#!/usr/bin/env python3
"""The Crypto Cut weekly recap.

Summarises the last seven daily editions (ending on the run date): what was
scanned, what fired, what made the cut, what we passed on and why, which cards
resolved this week, and the running record. Writes crypto/weekly/<end-date>.json
and sends one Telegram post and one email broadcast.

Each channel is sent at most once per week: crypto/data/weekly_sent.json is the
guard, so a retry run only sends what is missing.

Usage:
  python crypto/weekly.py                    # build + send
  python crypto/weekly.py --date YYYY-MM-DD  # recap the week ending on that date
  python crypto/weekly.py --build-only       # build files, send nothing
"""
import argparse
import collections
import datetime as dt
import html
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
import scan  # noqa: E402
import send  # noqa: E402

CFG = scan.CFG
SITE = scan.SITE
UTC = dt.timezone.utc
WEEKLY = os.path.join(ROOT, "weekly")
SENT = os.path.join(ROOT, "data", "weekly_sent.json")
STATUS = {"open": "Open", "target": "Target hit", "stop": "Stopped", "time": "Time stop", "ambiguous": "Ambiguous"}


def short(d):
    return dt.date.fromisoformat(d).strftime("%a %d %b")


def build(end):
    start = end - dt.timedelta(days=6)
    days = []
    for i in range(7):
        d = (start + dt.timedelta(days=i)).isoformat()
        p = os.path.join(ROOT, "editions", f"{d}.json")
        if os.path.exists(p):
            days.append(json.load(open(p)))
    cards = scan.load_json(os.path.join(ROOT, "data", "cards.json"), [])
    in_week = lambda d: d and start.isoformat() <= d <= end.isoformat()

    published = [c for c in cards if c["kind"] == "published" and in_week(c["edition_date"])]
    resolved = [c for c in cards if c.get("status") not in (None, "open") and in_week(c.get("resolved"))]
    res_pub = [c for c in resolved if c["kind"] == "published"]
    res_cut = [c for c in resolved if c["kind"] == "cut"]

    fell = collections.Counter()
    labels = {}
    reasons = collections.Counter()
    cut_coins = collections.Counter()
    fired_coins = collections.Counter()
    for e in days:
        for ch in e["checks"]:
            fell[ch["key"]] += ch["fell"]
            labels[ch["key"]] = ch["label"]
        for x in e["cut"]:
            reasons[x["reason"]] += 1
            cut_coins[x["symbol"]] += 1
            fired_coins[x["symbol"]] += 1

    latest = days[-1] if days else scan.load_json(os.path.join(ROOT, "editions", "latest.json"), None)
    w = {
        "week_start": start.isoformat(), "week_end": end.isoformat(),
        "editions": len(days),
        "quiet_days": sum(1 for e in days if e["counts"]["cleared"] == 0),
        "scanned_avg": round(sum(e["counts"]["scanned"] for e in days) / len(days)) if days else 0,
        "fired": sum(e["counts"]["fired"] for e in days),
        "cleared": sum(e["counts"]["cleared"] for e in days),
        "cut": sum(e["counts"]["cut"] for e in days),
        "days": [{"date": e["edition_date"], "day": e["day"], "fired": e["counts"]["fired"],
                  "cleared": e["counts"]["cleared"], "symbols": [k["symbol"] for k in e["cards"]]} for e in days],
        "published": [{k: c.get(k) for k in ("edition_date", "symbol", "entry", "stop", "target", "rr", "size_pct", "status", "r")}
                      for c in published],
        "resolved_published": [{k: c.get(k) for k in ("edition_date", "symbol", "status", "r", "resolved")} for c in res_pub],
        "resolved_cut": {"count": len(res_cut),
                         "avg_r": round(sum(c["r"] for c in res_cut if c["r"] is not None) /
                                        max(1, sum(1 for c in res_cut if c["r"] is not None)), 2) if res_cut else None},
        "checks": [{"key": k, "label": labels[k], "fell": fell[k]} for k in labels],
        "top_reasons": reasons.most_common(4),
        "most_active": fired_coins.most_common(5),
        "record": latest["record"] if latest else None,
        "window_day": latest["day"] if latest else None,
        "window_days": CFG["window_days"],
    }
    return w


def record_line(w):
    r = w["record"]
    if not r:
        return "No record yet."
    p, n = r["published"], r["min_n_to_report"]
    if p["resolved"] < n:
        return f"Not enough resolved cards to report a record yet ({p['resolved']} of {n}). {p['open']} published card(s) still open."
    cut = f"{r['cut']['avg_r']:+.2f}R" if r["cut"]["avg_r"] is not None else "n/a"
    return f"Published cards average {p['avg_r']:+.2f}R over {p['resolved']} resolved, against {cut} for The Cut."


def headline(w):
    if w["cleared"] == 0:
        return f"Nothing made the cut this week. {w['fired']} fired across {w['editions']} editions."
    return f"{w['cleared']} made the cut this week, out of {w['fired']} that fired."


def telegram_text(w):
    out = [f"📈 <b>THE CRYPTO CUT · WEEKLY</b>",
           f"<i>{short(w['week_start'])} to {short(w['week_end'])} · day {w['window_day']} of {w['window_days']}</i>", "",
           f"<b>{html.escape(headline(w))}</b>", "",
           f"🔍 {w['editions']} editions · about {w['scanned_avg']} coins scanned each day",
           f"⚡ Fired {w['fired']} → ✅ Qualified {w['cleared']} · 😴 {w['quiet_days']} quiet day(s)", ""]
    if w["published"]:
        out.append("<b>THIS WEEK'S CARDS</b>")
        for c in w["published"]:
            st = STATUS.get(c["status"], c["status"])
            if c.get("r") is not None and c["status"] != "open":
                st += f" {c['r']:+.2f}R"
            out.append(f"🟢 {c['symbol']} ({short(c['edition_date'])}): 🛑 {scan.fmt_price(c['stop'])} · 🎯 {scan.fmt_price(c['target'])} · {st}")
        out.append("")
    if w["resolved_published"]:
        out.append("<b>RESOLVED THIS WEEK</b>")
        for c in w["resolved_published"]:
            r = f" {c['r']:+.2f}R" if c.get("r") is not None else ""
            out.append(f"· {c['symbol']} from {short(c['edition_date'])}: {STATUS.get(c['status'], c['status'])}{r}")
        out.append("")
    hits = [c for c in w["checks"] if c["fell"]]
    if hits:
        out.append("<b>WHERE THE WEEK WAS CUT</b>")
        for c in sorted(hits, key=lambda c: -c["fell"]):
            out.append(f"× {c['label']}: {c['fell']} fell")
        out.append("")
    if w["most_active"]:
        out.append("✂️ <b>MOST ACTIVE, NOT PUBLISHED</b>")
        out.append(", ".join(f"{s} ({n}x)" for s, n in w["most_active"]))
        out.append("")
    out += [f"📈 {record_line(w)}", "",
            "🟡 Validation window. Unproven. Research and general commentary, identical for every reader. Not investment advice.",
            f"Every edition: {SITE}/#archive"]
    return "\n".join(out)


def email_text(w):
    t = telegram_text(w)
    for tag in ("<b>", "</b>", "<i>", "</i>"):
        t = t.replace(tag, "")
    return html.unescape(t)


def email_html(w):
    esc = html.escape
    ink, dim, red, teal = "#111111", "#666666", "#C0392B", "#0a8f74"
    td = f"padding:6px 8px;border-bottom:1px solid #eeeeee;font-family:Arial,Helvetica,sans-serif;font-size:13px;color:{ink}"
    days = "".join(f'<tr><td style="{td}">{esc(short(d["date"]))}</td><td style="{td}">{d["fired"]}</td>'
                   f'<td style="{td}">{d["cleared"]}</td><td style="{td}">{esc(", ".join(d["symbols"]) or "None")}</td></tr>'
                   for d in w["days"])
    cards = ""
    for c in w["published"]:
        st = STATUS.get(c["status"], c["status"])
        if c.get("r") is not None and c["status"] != "open":
            st += f" {c['r']:+.2f}R"
        cards += (f'<tr><td style="{td};font-weight:bold">{esc(c["symbol"])}</td><td style="{td}">{esc(short(c["edition_date"]))}</td>'
                  f'<td style="{td};color:{red}">{scan.fmt_price(c["stop"])}</td><td style="{td}">{scan.fmt_price(c["target"])}</td>'
                  f'<td style="{td}">{c["rr"]:.1f}x</td><td style="{td}">{esc(st)}</td></tr>')
    cards_block = (f'<table width="100%" cellpadding="0" cellspacing="0" border="0"><tr><th align="left" style="{td};color:{dim}">Coin</th>'
                   f'<th align="left" style="{td};color:{dim}">Date</th><th align="left" style="{td};color:{dim}">Stop</th>'
                   f'<th align="left" style="{td};color:{dim}">Target</th><th align="left" style="{td};color:{dim}">Reward</th>'
                   f'<th align="left" style="{td};color:{dim}">Result</th></tr>{cards}</table>') if cards else \
        f'<p style="margin:0;font-family:Arial,Helvetica,sans-serif;font-size:14px;color:{ink}">No card made the cut this week. That is the usual result, and the reason the cards that do get through mean something.</p>'
    resolved = "".join(f'<li>{esc(c["symbol"])} from {esc(short(c["edition_date"]))}: {esc(STATUS.get(c["status"], c["status"]))}'
                       f'{" " + format(c["r"], "+.2f") + "R" if c.get("r") is not None else ""}</li>' for c in w["resolved_published"])
    checks = "".join(f'<li>{esc(c["label"])}: {c["fell"]} fell</li>' for c in sorted(w["checks"], key=lambda c: -c["fell"]) if c["fell"])
    active = ", ".join(f"{esc(s)} ({n}x)" for s, n in w["most_active"]) or "Nothing fired."
    p = f'font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:22px;color:{ink};margin:0 0 10px'
    h = f'font-family:Arial,Helvetica,sans-serif;font-size:12px;font-weight:bold;letter-spacing:2px;color:{ink};margin:22px 0 8px'
    addr = esc(os.environ.get("SIGNAL_POSTAL_ADDRESS", ""))
    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0;background:#f4f4f4"><table width="100%" cellpadding="0" cellspacing="0" border="0"><tr><td align="center" style="padding:24px 12px">
<table width="600" cellpadding="0" cellspacing="0" border="0" style="max-width:600px;background:#ffffff;border-radius:10px">
<tr><td style="padding:28px 32px 12px;border-bottom:2px solid #0b3d33">
<div style="font-family:Arial,Helvetica,sans-serif;font-size:24px;font-weight:bold;letter-spacing:6px;color:{ink}">CRYPTO WISDOM</div>
<div style="font-family:'Courier New',monospace;font-size:13px;letter-spacing:3px;color:{ink};margin-top:6px">THE CRYPTO CUT · WEEKLY · {esc(short(w['week_start']).upper())} TO {esc(short(w['week_end']).upper())}</div></td></tr>
<tr><td style="padding:22px 32px 6px">
<p style="font-family:Arial,Helvetica,sans-serif;font-size:20px;line-height:28px;font-weight:bold;color:{ink};margin:0 0 10px">{esc(headline(w))}</p>
<p style="{p}">{w['editions']} editions, about {w['scanned_avg']} coins scanned each day. {w['fired']} fired, {w['cleared']} qualified, {w['quiet_days']} quiet day(s). Validation window day {w['window_day']} of {w['window_days']}.</p>
<div style="{h}">THE WEEK, DAY BY DAY</div>
<table width="100%" cellpadding="0" cellspacing="0" border="0"><tr><th align="left" style="{td};color:{dim}">Day</th><th align="left" style="{td};color:{dim}">Fired</th><th align="left" style="{td};color:{dim}">Made it</th><th align="left" style="{td};color:{dim}">Coins</th></tr>{days}</table>
<div style="{h}">THIS WEEK'S CARDS</div>{cards_block}
{f'<div style="{h}">RESOLVED THIS WEEK</div><ul style="{p}">{resolved}</ul>' if resolved else ''}
{f'<div style="{h}">WHERE THE WEEK WAS CUT</div><ul style="{p}">{checks}</ul>' if checks else ''}
<div style="{h}">MOST ACTIVE, NOT PUBLISHED</div><p style="{p}">{active}</p>
<div style="{h}">THE RECORD</div><p style="{p}">{esc(record_line(w))}</p>
<p style="{p}"><a href="{SITE}/#archive" style="color:{teal}">Every edition and the full record</a></p>
</td></tr>
<tr><td style="padding:16px 32px 28px;border-top:1px solid #eeeeee;font-family:Arial,Helvetica,sans-serif;font-size:12px;line-height:19px;color:{dim}">
Validation window: the record is unproven. Every reader receives this identical note. It is research and general commentary, not investment advice, and crypto assets can lose most or all of their value.<br>
<a href="{SITE}/" style="color:{teal}">{CFG['site']}</a>{' · ' + addr if addr else ''}<br>
<a href="{{{{{{RESEND_UNSUBSCRIBE_URL}}}}}}" style="color:{dim}">Unsubscribe</a></td></tr>
</table></td></tr></table></body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--build-only", action="store_true")
    a = ap.parse_args()
    end = dt.date.fromisoformat(a.date) if a.date else dt.datetime.now(UTC).date()
    w = build(end)
    if w["editions"] == 0:
        print("no editions in the week; nothing to recap")
        return 0
    key = w["week_end"]
    scan.save_json(os.path.join(WEEKLY, f"{key}.json"), w)
    idx = scan.load_json(os.path.join(WEEKLY, "index.json"), [])
    idx = [x for x in idx if x["week_end"] != key]
    idx.insert(0, {"week_start": w["week_start"], "week_end": key, "editions": w["editions"],
                   "fired": w["fired"], "cleared": w["cleared"]})
    idx.sort(key=lambda x: x["week_end"], reverse=True)
    scan.save_json(os.path.join(WEEKLY, "index.json"), idx)
    print(f"weekly {w['week_start']}..{key}: {w['editions']} editions, fired {w['fired']}, cleared {w['cleared']}")
    if a.build_only:
        print(telegram_text(w))
        return 0

    sent = scan.load_json(SENT, {})
    done = sent.setdefault(key, {})
    dry = send.env("DRY_RUN") == "1"
    failures = []
    tg_token, tg_chan = send.env("TELEGRAM_BOT_TOKEN"), send.env("CRYPTO_TELEGRAM_CHANNEL_ID")
    rs_key, rs_seg = send.env("RESEND_API_KEY"), send.env("CRYPTO_RESEND_SEGMENT_ID")

    if done.get("telegram"):
        print("telegram: already sent for week", key)
    elif not (tg_token and tg_chan) or dry:
        print("telegram: skipped")
    else:
        try:
            send.send_telegram(tg_token, tg_chan, "", "", telegram_text(w))
            done["telegram"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            print("telegram: sent")
        except Exception as ex:  # noqa: BLE001
            failures.append(f"telegram: {ex}")

    if done.get("email"):
        print("email: already sent for week", key)
    elif not (rs_key and rs_seg) or dry:
        print("email: skipped")
    else:
        subject = f"The Crypto Cut weekly · {short(w['week_start'])} to {short(key)}: " + (
            "nothing made the cut" if w["cleared"] == 0 else f"{w['cleared']} made the cut")
        try:
            done["email"] = send.send_email(rs_key, rs_seg, send.env("CRYPTO_FROM") or "The Crypto Cut <cut@mail.financewisdom.io>",
                                            subject, email_html(w), email_text(w), f"Crypto Cut weekly {key}")
            print("email: sent", done["email"])
        except Exception as ex:  # noqa: BLE001
            failures.append(f"email: {ex}")

    scan.save_json(SENT, sent)
    for f in failures:
        print("FAILED", f)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
