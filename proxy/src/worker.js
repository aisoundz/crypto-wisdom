/**
 * Crypto Wisdom Proxy — Cloudflare Worker
 *
 * Sits between cryptowisdom.io and Anthropic's API. Holds the API key as a
 * server-side secret so visitors never need their own. Rate-limits per IP
 * to cap daily cost.
 *
 * Endpoints:
 *   POST /v1/messages   — proxied to Anthropic /v1/messages
 *   GET  /v1/quota      — returns current visitor's quota usage (JSON)
 *   OPTIONS *           — CORS preflight
 *
 * Bindings expected (set in wrangler.toml + via wrangler secret):
 *   env.WISDOM_KV          — KV namespace for rate-limit counters
 *   env.ANTHROPIC_API_KEY  — secret, set via `wrangler secret put`
 */

const ALLOWED_ORIGINS = [
  'https://cryptowisdom.io',
  'http://cryptowisdom.io',
  'https://www.cryptowisdom.io',
  'http://www.cryptowisdom.io',
  // Allow the GitHub Pages dev URL so you can test pre-launch:
  'https://aisoundz.github.io',
];

const FREE_DAILY_LIMIT     = 5;          // messages per IP per UTC day
const ANTHROPIC_MODEL      = 'claude-sonnet-5-5';  // see env override below
// Was 'claude-sonnet-4-20250514' until 2026-10-14. That model was retired on
// 15 June 2026, and because line ~121 forces it onto every request, the free
// tier returned 404 not_found_error to every visitor for roughly four months.
// Nothing surfaced it: the Worker passes Anthropic's error through as a normal
// response, so Cloudflare's error metric stayed at 0, and the app renders a 404
// as the vague 'Model unavailable'.
const MAX_TOKENS_CAP       = 1500;       // hard cap to bound spend per call
const KV_QUOTA_TTL_SECONDS = 90000;      // 25h — auto-expires day after
const KV_CACHE_PREFIX      = 'cache:';
const CACHE_DEFAULT_TTL    = 12 * 3600;  // 12h default for cached responses
const CACHE_MIN_TTL        = 60;         // 1 min floor
const CACHE_MAX_TTL        = 86400;      // 24h ceiling

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const origin = request.headers.get('Origin') || '';
    const cors = corsHeaders(origin);

    // --- CORS preflight ---
    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: cors });
    }

    // --- Origin allowlist (only enforced when Origin header present) ---
    if (origin && !ALLOWED_ORIGINS.includes(origin)) {
      return jsonResp({ error: 'origin_not_allowed', origin }, 403, cors);
    }

    const ip = request.headers.get('CF-Connecting-IP') || 'unknown';
    const today = new Date().toISOString().slice(0, 10);   // YYYY-MM-DD UTC
    const kvKey = `q:${today}:${ip}`;

    // --- GET /v1/quota — visitor's current usage ---
    if (request.method === 'GET' && url.pathname === '/v1/quota') {
      const used = parseInt((await env.WISDOM_KV.get(kvKey)) || '0', 10);
      return jsonResp({
        used,
        limit: FREE_DAILY_LIMIT,
        remaining: Math.max(0, FREE_DAILY_LIMIT - used),
        resets_at: nextUtcMidnight(),
      }, 200, cors);
    }

    // --- POST /v1/messages — the main proxy ---
    if (request.method === 'POST' && url.pathname === '/v1/messages') {
      // Parse body first — we need cache_key before deciding whether to count quota
      let body;
      try { body = await request.json(); }
      catch { return jsonResp({ error: { type: 'invalid_json' } }, 400, cors); }

      if (!body.messages || !Array.isArray(body.messages)) {
        return jsonResp({ error: { type: 'missing_messages' } }, 400, cors);
      }

      // Pull out caching params (sent by the front-end, NOT forwarded to Anthropic)
      const cacheKey = typeof body.cache_key === 'string' ? body.cache_key.slice(0, 200) : null;
      const cacheTtl = cacheKey
        ? Math.min(Math.max(parseInt(body.cache_ttl_seconds || CACHE_DEFAULT_TTL, 10), CACHE_MIN_TTL), CACHE_MAX_TTL)
        : 0;
      delete body.cache_key;
      delete body.cache_ttl_seconds;

      // ── Cache-hit path: free, no quota deduction, no upstream call ──
      if (cacheKey) {
        const cached = await env.WISDOM_KV.get(KV_CACHE_PREFIX + cacheKey);
        if (cached) {
          const used = parseInt((await env.WISDOM_KV.get(kvKey)) || '0', 10);
          return new Response(cached, {
            status: 200,
            headers: {
              ...cors,
              'Content-Type':          'application/json',
              'X-Wisdom-Cache':        'HIT',
              'X-Wisdom-Cache-Key':    cacheKey,
              'X-Wisdom-Quota-Used':   String(used),
              'X-Wisdom-Quota-Limit':  String(FREE_DAILY_LIMIT),
              'X-Wisdom-Quota-Resets': nextUtcMidnight(),
            },
          });
        }
      }

      // ── Cache miss (or no cache requested): apply per-IP quota ──
      const used = parseInt((await env.WISDOM_KV.get(kvKey)) || '0', 10);
      if (used >= FREE_DAILY_LIMIT) {
        return jsonResp({
          error: { type: 'free_quota_exceeded', message:
            `You've used your ${FREE_DAILY_LIMIT} free Wisdom messages today. ` +
            `Bring your own Anthropic API key for unlimited access, or come back tomorrow.` },
          quota: {
            used, limit: FREE_DAILY_LIMIT, remaining: 0,
            resets_at: nextUtcMidnight(),
          },
        }, 429, cors);
      }

      // Force/cap the dangerous params so a bad client can't run up the bill
      // env.ANTHROPIC_MODEL lets this be changed from the Cloudflare dashboard
      // (Settings > Variables) without a code deploy, which is what made the
      // stale pin above so slow to fix. Still SERVER controlled: the client's
      // own body.model is always discarded, so a visitor cannot pick an
      // expensive model and run up the bill on the free tier.
      body.model      = env.ANTHROPIC_MODEL || ANTHROPIC_MODEL;
      body.max_tokens = Math.min(parseInt(body.max_tokens || 800, 10), MAX_TOKENS_CAP);

      // Forward to Anthropic
      const upstream = await fetch('https://api.anthropic.com/v1/messages', {
        method: 'POST',
        headers: {
          'Content-Type':       'application/json',
          'x-api-key':          env.ANTHROPIC_API_KEY,
          'anthropic-version':  '2023-06-01',
        },
        body: JSON.stringify(body),
      });

      const upstreamBody = await upstream.text();

      // On success: increment per-IP quota AND store cache (if requested)
      let newUsed = used;
      if (upstream.ok) {
        newUsed = used + 1;
        ctx.waitUntil(env.WISDOM_KV.put(kvKey, String(newUsed),
          { expirationTtl: KV_QUOTA_TTL_SECONDS }));
        if (cacheKey) {
          ctx.waitUntil(env.WISDOM_KV.put(KV_CACHE_PREFIX + cacheKey, upstreamBody,
            { expirationTtl: cacheTtl }));
        }
      }

      const respHeaders = {
        ...cors,
        'Content-Type':          'application/json',
        'X-Wisdom-Cache':        cacheKey ? 'MISS' : 'BYPASS',
        'X-Wisdom-Quota-Used':   String(newUsed),
        'X-Wisdom-Quota-Limit':  String(FREE_DAILY_LIMIT),
        'X-Wisdom-Quota-Resets': nextUtcMidnight(),
      };
      if (cacheKey) respHeaders['X-Wisdom-Cache-Key'] = cacheKey;

      return new Response(upstreamBody, { status: upstream.status, headers: respHeaders });
    }

    // --- Anything else ---
    return jsonResp({ error: 'not_found' }, 404, cors);
  },
};

// ----- helpers -----

function corsHeaders(origin) {
  const allowed = ALLOWED_ORIGINS.includes(origin) ? origin : ALLOWED_ORIGINS[0];
  return {
    'Access-Control-Allow-Origin':   allowed,
    'Access-Control-Allow-Methods':  'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers':  'Content-Type',
    'Access-Control-Expose-Headers': 'X-Wisdom-Quota-Used, X-Wisdom-Quota-Limit, X-Wisdom-Quota-Resets',
    'Access-Control-Max-Age':        '86400',
    'Vary':                          'Origin',
  };
}

function jsonResp(obj, status, extraHeaders) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { ...(extraHeaders || {}), 'Content-Type': 'application/json' },
  });
}

function nextUtcMidnight() {
  const d = new Date();
  d.setUTCHours(24, 0, 0, 0);
  return d.toISOString();
}
