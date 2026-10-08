#!/usr/bin/env python3
"""Send today's Crypto Cut to Telegram and email (Resend).

Each channel decides on its own whether it can send, and each is sent at most once
per edition: crypto/data/sent.json records what already went out, so a retry run
only sends what is missing. Refuses to send anything if out/GATE_FAILED exists.
"""
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.request
import uuid

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "out")
SENT = os.path.join(ROOT, "data", "sent.json")


def env(k):
    return (os.environ.get(k) or "").strip()


def http(url, data=None, headers=None, method=None, retries=4):
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")[:300]
            last = f"HTTP {e.code}: {body}"
            if e.code < 500 and e.code != 429:
                break
        except Exception as e:  # noqa: BLE001
            last = str(e)
        time.sleep(2 ** i)
    raise RuntimeError(last)


def multipart(fields, files):
    b = uuid.uuid4().hex
    parts = []
    for k, v in fields.items():
        parts.append(f"--{b}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode())
    for k, path in files.items():
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        parts.append(f"--{b}\r\nContent-Disposition: form-data; name=\"{k}\"; filename=\"{os.path.basename(path)}\"\r\n"
                     f"Content-Type: {ctype}\r\n\r\n".encode() + open(path, "rb").read() + b"\r\n")
    parts.append(f"--{b}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={b}"


def send_telegram(token, chat, png, caption, text):
    api = f"https://api.telegram.org/bot{token}"
    if os.path.exists(png):
        body, ctype = multipart({"chat_id": chat, "caption": caption, "parse_mode": "HTML"}, {"photo": png})
        http(api + "/sendPhoto", body, {"Content-Type": ctype})
    payload = json.dumps({"chat_id": chat, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}).encode()
    http(api + "/sendMessage", payload, {"Content-Type": "application/json"})


def send_email(key, segment, sender, subject, html_body, text_body, name):
    h = {"Authorization": f"Bearer {key}", "Content-Type": "application/json", "User-Agent": "crypto-cut/1.0"}
    payload = {"segment_id": segment, "from": sender, "subject": subject,
               "html": html_body, "text": text_body, "name": name}
    if env("CRYPTO_REPLY_TO"):
        payload["reply_to"] = env("CRYPTO_REPLY_TO")
    b = http("https://api.resend.com/broadcasts", json.dumps(payload).encode(), h, "POST")
    http(f"https://api.resend.com/broadcasts/{b['id']}/send", b"{}", h, "POST")
    return b["id"]


def main():
    if os.path.exists(os.path.join(OUT, "GATE_FAILED")):
        print("refusing to send: GATE_FAILED")
        return 2
    e = json.load(open(os.path.join(ROOT, "editions", "latest.json")))
    date = e["edition_date"]
    sent = json.load(open(SENT)) if os.path.exists(SENT) else {}
    done = sent.setdefault(date, {})
    dry = env("DRY_RUN") == "1"

    tg_token, tg_chan = env("TELEGRAM_BOT_TOKEN"), env("CRYPTO_TELEGRAM_CHANNEL_ID")
    rs_key, rs_seg = env("RESEND_API_KEY"), env("CRYPTO_RESEND_SEGMENT_ID")
    failures = []

    if done.get("telegram"):
        print("telegram: already sent for", date)
    elif not (tg_token and tg_chan):
        print("telegram: skipped (CRYPTO_TELEGRAM_CHANNEL_ID or TELEGRAM_BOT_TOKEN not set)")
    elif dry:
        print("telegram: dry run")
    else:
        try:
            send_telegram(tg_token, tg_chan, os.path.join(ROOT, "editions", f"{date}.png"),
                          open(os.path.join(OUT, "caption.txt")).read(), open(os.path.join(OUT, "telegram.txt")).read())
            done["telegram"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            print("telegram: sent")
        except Exception as ex:  # noqa: BLE001
            failures.append(f"telegram: {ex}")

    if done.get("email"):
        print("email: already sent for", date)
    elif not (rs_key and rs_seg):
        print("email: skipped (CRYPTO_RESEND_SEGMENT_ID or RESEND_API_KEY not set)")
    elif dry:
        print("email: dry run")
    else:
        c = e["counts"]
        subject = (f"The Crypto Cut · {date}: nothing made the cut" if c["cleared"] == 0
                   else f"The Crypto Cut · {date}: {c['cleared']} made the cut")
        try:
            bid = send_email(rs_key, rs_seg, env("CRYPTO_FROM") or "The Crypto Cut <cut@mail.financewisdom.io>",
                             subject, open(os.path.join(OUT, "email.html")).read(),
                             open(os.path.join(OUT, "email.txt")).read(), f"Crypto Cut {date}")
            done["email"] = bid
            print("email: sent", bid)
        except Exception as ex:  # noqa: BLE001
            failures.append(f"email: {ex}")

    os.makedirs(os.path.dirname(SENT), exist_ok=True)
    json.dump(sent, open(SENT, "w"), indent=1)
    for f in failures:
        print("FAILED", f)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
