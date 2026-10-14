# cryptowisdom-proxy

The Cloudflare Worker behind Crypto Wisdom's free tier. It holds the Anthropic
key server-side so a visitor gets 5 messages a day without pasting a key of
their own, rate-limits per IP through KV, and caps spend per call.

## Why it is in this repository now

It was not, until 2026-10-14. It lived in `~/Documents/Projects/cryptowisdom-proxy`
on one laptop, deployed by hand five months earlier.

The cost of that: `ANTHROPIC_MODEL` was pinned to `claude-sonnet-4-20250514`,
which Anthropic retired on 15 June 2026. Line 132 forces that model onto every
request, so **every free-tier visitor got a 404 for roughly four months**, and
four separate signals said everything was fine:

- the app's `Active` badge is set unconditionally, so it reads Active regardless
- Cloudflare's error count stayed at **0**, because the Worker passes Anthropic's
  error through as an ordinary response
- the app renders a 404 as "Model unavailable", which reads as a passing glitch
- the message composer was unreachable behind the fixed nav bar anyway

None of those is a check. `test_worker_contract.mjs` is, and it fails on exactly
that state.

## Layout

| | |
|---|---|
| `src/worker.js` | the Worker |
| `wrangler.toml` | name, entrypoint, KV binding |
| `test_worker_contract.mjs` | the invariants, run by CI and before any deploy |
| `DEPLOY.md` | the original first-time setup notes |

## Changing the model

Two places have to agree, and the contract test enforces it:

- `ANTHROPIC_MODEL` here, the default for the free tier
- `CW_MODEL` in `app/index.html`, used when a visitor brings their own key

For an urgent change with no deploy, set `ANTHROPIC_MODEL` as a **Variable** on
the Worker in the Cloudflare dashboard. Line 132 reads `env.ANTHROPIC_MODEL`
first and falls back to the constant. Still server-controlled: the client's own
`body.model` is always discarded, so a visitor can never pick an expensive model
and bill it to you.

## Deploying

Run the **Deploy the Wisdom proxy** workflow. It needs a `CLOUDFLARE_API_TOKEN`
secret on this repository ("Edit Cloudflare Workers" template). It runs the
contract first, and after deploying it calls the live Worker and reads the model
back out of the response, because a green deploy proved nothing for four months.

`ANTHROPIC_API_KEY` is a Worker secret (`wrangler secret put`), never in source,
and is untouched by deploys.
