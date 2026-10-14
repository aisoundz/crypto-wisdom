# Crypto Wisdom Proxy — Deploy

This deploys a Cloudflare Worker that serves as the rate-limited, server-side
proxy between cryptowisdom.io and Anthropic's API. After this is live, your
visitors can use Wisdom for 5 messages/day without ever entering an API key.

Estimated time: **15–20 minutes**.

You'll run all of this from a terminal on your Mac (not Claude Code, just
plain Terminal / iTerm).

---

## Prereqs

- A Cloudflare account (you said you have one ✓)
- Node.js installed (test: `node --version` — should be ≥ 18)
- Your Anthropic API key handy (the same `sk-ant-…` key you've been using
  for testing — you'll set it as a Worker secret, never in source code)

---

## Step 1 — Get the proxy code onto your Mac

The two files (`src/worker.js` and `wrangler.toml`) are in this folder:

```
~/Downloads/Instagram Post - 50%/crypto-wisdom-launch/proxy/
├── DEPLOY.md           ← you are here
├── wrangler.toml
└── src/
    └── worker.js
```

Copy the whole `proxy` folder somewhere clean — don't work inside Downloads.
Recommended:

```bash
mkdir -p ~/Code
cp -r ~/Downloads/"Instagram Post - 50%"/crypto-wisdom-launch/proxy ~/Code/cryptowisdom-proxy
cd ~/Code/cryptowisdom-proxy
```

---

## Step 2 — Install Wrangler (Cloudflare's CLI)

```bash
npm install -g wrangler
wrangler --version
```

Should print something like `4.x.x`. If it errors, install Node first
(`brew install node` if you use Homebrew).

---

## Step 3 — Log in to Cloudflare

```bash
wrangler login
```

A browser window opens, you click **Allow** to grant Wrangler access to
your Cloudflare account, terminal returns to a prompt. Done.

---

## Step 4 — Create the KV namespace (rate-limit storage)

```bash
wrangler kv namespace create WISDOM_KV
```

Output looks like:

```
🌀 Creating namespace with title "cryptowisdom-proxy-WISDOM_KV"
✨ Success!
Add the following to your configuration file in your kv_namespaces array:
{
  binding = "WISDOM_KV",
  id = "abc123def456..."
}
```

**Copy the `id` value.** Open `wrangler.toml` in a text editor and replace
`PASTE_KV_NAMESPACE_ID_HERE` with that id (keep the quotes around it).

---

## Step 5 — Set your Anthropic API key as a Worker secret

```bash
wrangler secret put ANTHROPIC_API_KEY
```

When prompted, paste your `sk-ant-…` key and press Enter. The key is
encrypted at rest in Cloudflare's vault and is only available to your
Worker code via `env.ANTHROPIC_API_KEY`. It's never written to disk
locally and never appears in logs.

---

## Step 6 — Deploy

```bash
wrangler deploy
```

Output ends with something like:

```
🌍 Deploying to Cloudflare's network...
✨ Successfully deployed!
   https://cryptowisdom-proxy.<your-subdomain>.workers.dev
```

**Copy that full URL** — it's the proxy's public endpoint. We'll wire the
front-end to call it in the next step. Looks something like:

```
https://cryptowisdom-proxy.aisoundz9.workers.dev
```

---

## Step 7 — Sanity-check it works

From the same terminal:

```bash
# Should return current quota (used: 0, limit: 5)
curl https://cryptowisdom-proxy.<your-subdomain>.workers.dev/v1/quota \
  -H "Origin: https://cryptowisdom.io"

# Should send a real Anthropic call and return the response
curl -X POST https://cryptowisdom-proxy.<your-subdomain>.workers.dev/v1/messages \
  -H "Origin: https://cryptowisdom.io" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "In 10 words: what is Crypto Wisdom?"}],
    "max_tokens": 100
  }'
```

If both return real JSON (the second includes Claude's actual response),
the proxy works.

If the first returns `{"error":"origin_not_allowed"}`, the `Origin` header
in your curl is being mangled — usually fine in a real browser, you can
ignore for the curl test.

---

## Step 8 — Tell me the Worker URL

Paste the URL from Step 6 back into our chat. I'll wire it into
`index.html`, push the change to GitHub, and we test end-to-end.

After that, the launch is fully frictionless: any visitor lands on
cryptowisdom.io and can use Wisdom immediately. No API key required.

---

## Optional polish (later this week, not required for launch)

### Custom domain (api.cryptowisdom.io)

Today we use the workers.dev subdomain. To put the proxy on
`api.cryptowisdom.io` instead (cleaner, on-brand), you'd need to migrate
cryptowisdom.io's DNS from GoDaddy to Cloudflare:

1. Add cryptowisdom.io as a site in your Cloudflare dashboard.
2. Cloudflare gives you 2 nameservers. Update them in GoDaddy → DNS →
   Nameservers.
3. Wait 1–24 hours for nameserver propagation.
4. Cloudflare automatically imports your existing DNS records.
5. In `wrangler.toml`, uncomment the `[[routes]]` block and re-deploy.

This is a 1-day project. Save it for next week — the workers.dev URL works
fine for launch.

### Tighter spend controls

If launch goes hard and you need to cap spend faster, edit `worker.js`:

- `FREE_DAILY_LIMIT = 5` → lower to 3 or 2
- `MAX_TOKENS_CAP = 1500` → lower to 800

Then `wrangler deploy` again — change is live in ~10 seconds.

### Per-tier auth (future)

The current proxy is anonymous (rate-limited by IP). When you launch
Founding Member tiers, swap the IP key for a session token from a Stripe
checkout flow. The Worker has access to `env.STRIPE_KEY` once you add it
as a secret, so this is a small addition rather than a rewrite.
