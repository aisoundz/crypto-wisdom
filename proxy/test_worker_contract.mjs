#!/usr/bin/env node
// The invariants this Worker has to keep. Run: node proxy/test_worker_contract.mjs
//
// Written on 2026-10-14, the day it was found that this Worker had been
// returning 404 to EVERY free-tier visitor since roughly 15 June 2026.
//
// The cause was one stale constant: ANTHROPIC_MODEL pinned to
// claude-sonnet-4-20250514, a model Anthropic retired, forced onto every
// request by the line that exists to stop a client choosing an expensive one.
// Four months, and four separate things said it was fine:
//
//   the app's "Active" badge is set unconditionally, so it reads Active
//     whether or not anything works
//   Cloudflare's error count stayed at 0, because the Worker passes
//     Anthropic's error through as an ordinary 200-path response
//   the app renders a 404 as "Model unavailable", which reads as a glitch
//   the composer was unreachable behind the nav bar anyway, so nobody got
//     far enough to see it
//
// None of those is a check. This file is. Every assertion below is something
// that, had it been running, would have caught a real defect this repo has
// actually had.
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(join(here, 'src/worker.js'), 'utf8');
const app = readFileSync(join(here, '../app/index.html'), 'utf8');

const failures = [];
const check = (name, cond, detail = '') => {
  console.log(`  ${cond ? 'ok  ' : 'FAIL'} ${name}${cond ? '' : `   ${detail}`}`);
  if (!cond) failures.push(name);
};

// Models known to be withdrawn. A pin to any of these is the exact outage of
// 2026-06 to 2026-10. Add to this list, never remove from it.
const RETIRED = ['claude-sonnet-4-20250514', 'claude-3-5-sonnet-20241022',
                 'claude-3-opus-20240229', 'claude-3-sonnet-20240229',
                 'claude-3-haiku-20240307', 'claude-2', 'claude-instant'];

console.log('== the model is not one that has been withdrawn ==');
const modelMatch = src.match(/const ANTHROPIC_MODEL\s*=\s*['"]([^'"]+)['"]/);
check('ANTHROPIC_MODEL is declared', !!modelMatch);
const model = modelMatch ? modelMatch[1] : '';
for (const dead of RETIRED) {
  check(`not pinned to ${dead}`, model !== dead,
        'this is the pin that returned 404 to every free-tier visitor for four months');
}
check('the model looks like a current-generation name',
      /^claude-(opus|sonnet|haiku|fable)-\d/.test(model), model);

console.log('\n== the app and the Worker agree on the model ==');
// They are separate paths: the Worker serves the free tier, CW_MODEL serves a
// visitor's own key. If they drift, two classes of user get different answers
// from the same product and nothing says so.
const cw = app.match(/var CW_MODEL\s*=\s*['"]([^'"]+)['"]/);
check('the app declares CW_MODEL', !!cw);
check('CW_MODEL matches the Worker default', cw && cw[1] === model,
      `app=${cw && cw[1]} worker=${model}`);

console.log('\n== a visitor cannot pick an expensive model on your key ==');
check('body.model is assigned server-side', /body\.model\s*=/.test(src));
check('and never taken from the client request',
      !/body\.model\s*=\s*body\.model/.test(src)
      && !/body\.model\s*\|\|/.test(src),
      'the free tier runs on the owner\'s key: client choice means client-set spend');
check('the override source is the environment, not the request',
      /body\.model\s*=\s*env\.ANTHROPIC_MODEL\s*\|\|\s*ANTHROPIC_MODEL/.test(src),
      'env is server-controlled and editable without a deploy');
check('max_tokens is capped', /body\.max_tokens\s*=\s*Math\.min\(/.test(src));
check('the cap constant exists', /const MAX_TOKENS_CAP/.test(src));
check('a daily free limit exists', /const FREE_DAILY_LIMIT/.test(src));

console.log('\n== no credential is in the source ==');
check('no sk-ant literal', !/sk-ant-[A-Za-z0-9_-]{10,}/.test(src),
      'the key belongs in a Worker secret, never here');
check('the key is read from env', /env\.ANTHROPIC_API_KEY/.test(src));

console.log('\n== CORS stays closed ==');
const originsBlock = (src.match(/const ALLOWED_ORIGINS\s*=\s*\[([\s\S]*?)\]/) || [])[1] || '';
check('an explicit origin allowlist exists', originsBlock.length > 0);
check('no wildcard origin', !/['"]\*['"]/.test(originsBlock),
      'a wildcard turns this into an open relay billed to the owner');
check('the production site is allowed',
      originsBlock.includes('https://cryptowisdom.io'));

console.log();
if (failures.length) {
  console.log(`${failures.length} FAILED: ${failures.join(', ')}`);
  process.exit(1);
}
console.log('all passed — the proxy cannot quietly serve a dead model, leak a key,\n'
          + 'become an open relay, or let a visitor choose what to spend');
