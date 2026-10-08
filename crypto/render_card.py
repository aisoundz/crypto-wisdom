#!/usr/bin/env python3
"""Render the day's Crypto Cut card (1080 x 1350 PNG) from editions/latest.json.

Refuses to render when out/GATE_FAILED exists: a card must never show rejected data.
Fonts come from the google/fonts GitHub repo and are embedded, so the card looks the
same on any runner.
"""
import base64
import html
import json
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "out")
FONT_DIR = os.path.join(ROOT, "fonts")
FONTS = {
    "Bebas Neue": "ofl/bebasneue/BebasNeue-Regular.ttf",
    "DM Mono": "ofl/dmmono/DMMono-Regular.ttf",
    "DM Sans": "ofl/dmsans/DMSans%5Bopsz,wght%5D.ttf",
}
MAX_ROWS = 5


def font_css():
    os.makedirs(FONT_DIR, exist_ok=True)
    css = []
    for fam, path in FONTS.items():
        local = os.path.join(FONT_DIR, fam.replace(" ", "") + ".ttf")
        if not os.path.exists(local):
            try:
                urllib.request.urlretrieve("https://raw.githubusercontent.com/google/fonts/main/" + path, local)
            except Exception as e:  # noqa: BLE001
                print(f"font {fam} unavailable ({e}); using fallback")
                continue
        b64 = base64.b64encode(open(local, "rb").read()).decode()
        css.append(f"@font-face{{font-family:'{fam}';src:url(data:font/ttf;base64,{b64}) format('truetype');font-weight:100 900}}")
    return "\n".join(css)


def price(p):
    if p >= 1000:
        return f"${p:,.0f}"
    if p >= 1:
        return f"${p:,.2f}"
    if p >= 0.01:
        return f"${p:.4f}"
    return f"${p:.8f}".rstrip("0")


def build_html(e):
    esc = html.escape
    c = e["counts"]
    n = c["cleared"]
    d = __import__("datetime").date.fromisoformat(e["edition_date"])
    date_s = d.strftime("%a %-d %b %Y").upper()
    if n == 0:
        h1 = "NOTHING MADE<br><span class='dim'>THE CUT TODAY.</span>"
        sub = f"{c['scanned']} liquid coins, scanned at the daily close. Nothing cleared every check."
    else:
        word = "ONE COIN" if n == 1 else f"{n} COINS"
        h1 = f"{word} MADE<br><span class='dim'>THE CUT.</span>"
        sub = f"{c['scanned']} liquid coins, scanned at the daily close. {c['fired']} fired, {n} cleared every check."

    if n == 0:
        body = ("<div class='box'><div class='bh'>AND THAT IS THE POINT.</div><p>Most days look like this. "
                "We do not publish to fill space. Hearing clearly that nothing is worth your attention is "
                "the most valuable thing we send.</p></div>")
    else:
        rows = ""
        for k in e["cards"][:MAX_ROWS]:
            rows += (f"<div class='card'><div class='sym'>{esc(k['symbol'])}<span class='det'>{esc(' · '.join(k['detectors']))}</span></div>"
                     f"<div class='lv'><div><i>ENTRY</i>{price(k['entry'])}</div>"
                     f"<div class='stop'><i>STOP</i>{price(k['stop'])}</div>"
                     f"<div><i>TARGET</i>{price(k['target'])}</div>"
                     f"<div><i>R:R · SIZE</i>{k['rr']:.1f}x · {k['size_pct']:.1f}%</div></div></div>")
        if len(e["cards"]) > MAX_ROWS:
            rows += f"<div class='more'>+ {len(e['cards']) - MAX_ROWS} more in the note below</div>"
        body = rows

    cut = "".join(f"<div class='chip'><b>{esc(x['symbol'])}</b><span>{esc(x['reason'])}</span></div>" for x in e["cut"][:4])
    cut_block = (f"<div class='lbl'>&#9656; THE CUT: WHAT WE PASSED ON</div><div class='chips'>{cut}</div>" if cut else "")

    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
{font_css()}
*{{box-sizing:border-box;margin:0;padding:0}}
html,body{{width:1080px;background:#000}}
body{{font-family:'DM Sans',Arial,sans-serif;color:#fff;padding:56px}}
.frame{{border-radius:36px;padding:72px 64px 48px;background:radial-gradient(circle at 85% 8%,rgba(0,212,170,.16),transparent 38%),linear-gradient(180deg,#0B0F0E,#050606 70%,#0B0A07)}}
.top{{display:flex;justify-content:space-between;align-items:flex-start;padding-bottom:28px;border-bottom:1px solid #222}}
.logo{{font-family:'Bebas Neue',Impact,sans-serif;font-size:56px;letter-spacing:.06em;line-height:1}}
.logo b{{color:#00D4AA;font-weight:400}}
.by{{font-family:'DM Mono',monospace;font-size:15px;letter-spacing:.3em;color:#888;margin-top:8px}}
.meta{{text-align:right;font-family:'DM Mono',monospace;font-size:17px;letter-spacing:.14em;line-height:1.8}}
.meta .day{{color:#00D4AA}}
h1{{font-family:'Bebas Neue',Impact,sans-serif;font-weight:400;font-size:132px;line-height:.94;margin:48px 0 22px;letter-spacing:.005em}}
.dim{{color:#B8BCC8}}
.sub{{font-size:24px;font-weight:300;color:#C8C8C8;line-height:1.45;margin-bottom:34px}}
.stats{{display:grid;grid-template-columns:repeat(3,1fr);gap:18px;margin-bottom:30px}}
.stat{{border:1px solid #2A2E36;border-radius:16px;padding:22px 26px}}
.stat .n{{font-family:'Bebas Neue',Impact,sans-serif;font-size:72px;line-height:1}}
.stat .l{{font-family:'DM Mono',monospace;font-size:14px;letter-spacing:.2em;color:#888;margin-top:8px}}
.stat.go .n{{color:#00D4AA}}
.box{{border:1px solid #2A2E36;border-radius:16px;padding:30px 30px;margin-bottom:34px}}
.bh{{font-family:'Bebas Neue',Impact,sans-serif;font-size:44px;margin-bottom:12px}}
.box p{{font-size:21px;font-weight:300;color:#C8C8C8;line-height:1.5}}
.card{{border:1px solid #1d4d43;background:rgba(0,212,170,.05);border-radius:16px;padding:20px 26px;margin-bottom:14px}}
.sym{{font-family:'Bebas Neue',Impact,sans-serif;font-size:46px;line-height:1;margin-bottom:12px}}
.det{{font-family:'DM Mono',monospace;font-size:14px;letter-spacing:.08em;color:#00D4AA;margin-left:16px;vertical-align:middle}}
.lv{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;font-family:'DM Mono',monospace;font-size:21px}}
.lv i{{display:block;font-style:normal;font-size:12px;letter-spacing:.2em;color:#888;margin-bottom:4px}}
.lv .stop{{color:#FF6B63}}
.more{{font-family:'DM Mono',monospace;font-size:17px;color:#888;margin:4px 0 26px}}
.lbl{{font-family:'DM Mono',monospace;font-size:14px;letter-spacing:.24em;color:#888;margin:20px 0 14px}}
.chips{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:34px}}
.chip{{border:1px solid #2A2E36;border-radius:12px;padding:14px 16px}}
.chip b{{display:block;font-family:'Bebas Neue',Impact,sans-serif;font-weight:400;font-size:28px}}
.chip span{{font-size:14px;color:#999}}
.foot{{display:flex;justify-content:space-between;align-items:center;border-top:1px solid #222;padding-top:24px;font-family:'DM Mono',monospace;font-size:14px;letter-spacing:.16em;color:#888}}
.badge{{color:#00D4AA;border:1px solid rgba(0,212,170,.4);border-radius:6px;padding:8px 14px}}
</style></head><body><div class="frame">
<div class="top"><div><div class="logo">CRYPTO <b>WISDOM</b></div><div class="by">THE CRYPTO CUT</div></div>
<div class="meta">{date_s}<br><span class="day">DAY {e['day']} / {e['window_days']}</span></div></div>
<h1>{h1}</h1><div class="sub">{esc(sub)}</div>
<div class="stats"><div class="stat"><div class="n">{c['scanned']}</div><div class="l">SCANNED</div></div>
<div class="stat"><div class="n">{c['fired']}</div><div class="l">FIRED</div></div>
<div class="stat go"><div class="n">{n}</div><div class="l">CLEARED</div></div></div>
{body}{cut_block}
<div class="foot"><span>CRYPTOWISDOM.IO</span><span class="badge">{esc(e['badge'])}</span></div>
</div></body></html>"""


def main():
    if os.path.exists(os.path.join(OUT, "GATE_FAILED")):
        print("refusing to render: GATE_FAILED")
        return 2
    e = json.load(open(os.path.join(ROOT, "editions", "latest.json")))
    page = os.path.join(OUT, "card.html")
    open(page, "w").write(build_html(e))
    from playwright.sync_api import sync_playwright
    png = os.path.join(ROOT, "editions", f"{e['edition_date']}.png")
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1080, "height": 1350}, device_scale_factor=1)
        pg.goto("file://" + page)
        pg.wait_for_timeout(300)
        h = min(2400, pg.evaluate("document.body.scrollHeight"))
        pg.set_viewport_size({"width": 1080, "height": max(1350, h)})
        pg.screenshot(path=png, full_page=False)
        b.close()
    print("card:", png)
    return 0


if __name__ == "__main__":
    sys.exit(main())
