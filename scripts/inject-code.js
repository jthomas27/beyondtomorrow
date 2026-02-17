#!/usr/bin/env node
/**
 * Ghost Code Injection Updater
 *
 * Pushes header.txt → Site Header and footer.txt → Site Footer
 * via Ghost Admin session auth (email/password login).
 *
 * Usage:
 *   node inject-code.js --email <email> --password <password>
 *
 * Ghost's settings API requires Owner/Admin session auth —
 * custom integration API keys cannot edit settings (returns 501).
 */

const https = require('https');
const fs = require('fs');
const path = require('path');

const GHOST_URL = 'https://beyondtomorrow.world';

// ── Parse CLI args ──
function parseArgs() {
  const args = process.argv.slice(2);
  const parsed = {};
  for (let i = 0; i < args.length; i += 2) {
    const key = args[i].replace(/^--/, '');
    parsed[key] = args[i + 1];
  }
  if (!parsed.email || !parsed.password) {
    console.error('Usage: node inject-code.js --email <email> --password <password>');
    process.exit(1);
  }
  return parsed;
}

// ── HTTP helper (supports cookie auth) ──
function request(method, urlPath, body, extraHeaders = {}) {
  return new Promise((resolve, reject) => {
    const url = new URL(urlPath, GHOST_URL);
    const options = {
      method,
      hostname: url.hostname,
      path: url.pathname + url.search,
      headers: {
        'Content-Type': 'application/json',
        'Origin': GHOST_URL,
        ...extraHeaders,
      },
    };

    const req = https.request(options, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        const cookies = res.headers['set-cookie'];
        try {
          resolve({ status: res.statusCode, data: data ? JSON.parse(data) : null, cookies });
        } catch {
          resolve({ status: res.statusCode, data, cookies });
        }
      });
    });
    req.on('error', reject);
    if (body) req.write(JSON.stringify(body));
    req.end();
  });
}

// ── Session login ──
async function login(email, password) {
  console.log('\n🔐 Logging in via session auth...');
  const res = await request('POST', '/ghost/api/admin/session/', {
    username: email,
    password: password,
  });

  if (res.status === 201 && res.cookies) {
    const cookie = res.cookies.map(c => c.split(';')[0]).join('; ');
    console.log('   ✅ Logged in successfully');
    return cookie;
  }

  if (res.status === 403) {
    console.error('   ❌ 403 — Device verification may be required.');
    console.error('   Check your email for a verification link, then try again.');
    process.exit(1);
  }

  if (res.status === 429) {
    console.error('   ❌ 429 — Rate limited. Wait a few minutes and try again.');
    process.exit(1);
  }

  console.error(`   ❌ Login failed (HTTP ${res.status}):`, JSON.stringify(res.data, null, 2));
  process.exit(1);
}

// ── Main ──
async function main() {
  console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
  console.log('  Ghost Code Injection — BeyondTomorrow.World');
  console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');

  const { email, password } = parseArgs();

  // 1. Login
  const cookie = await login(email, password);

  // 2. Read source files
  const headerPath = path.join(__dirname, '..', 'theme', 'header.txt');
  const footerPath = path.join(__dirname, '..', 'theme', 'footer.txt');

  const headerCode = fs.existsSync(headerPath) ? fs.readFileSync(headerPath, 'utf-8') : '';
  const footerCode = fs.existsSync(footerPath) ? fs.readFileSync(footerPath, 'utf-8') : '';

  if (!headerCode && !footerCode) {
    console.error('❌ No header.txt or footer.txt found. Nothing to inject.');
    process.exit(1);
  }

  console.log(`\n📄 Header: ${headerCode.length} chars from header.txt`);
  console.log(`📄 Footer: ${footerCode.length} chars from footer.txt`);

  // 3. Push code injection
  console.log('\n🚀 Pushing code injection...');
  const res = await request('PUT', '/ghost/api/admin/settings/', {
    settings: [
      { key: 'codeinjection_head', value: headerCode },
      { key: 'codeinjection_foot', value: footerCode },
    ]
  }, { Cookie: cookie });

  if (res.status === 200) {
    console.log('✅ Code injection updated successfully');

    // 4. Verify
    const verify = await request('GET', '/ghost/api/admin/settings/', null, { Cookie: cookie });
    if (verify.status === 200) {
      const settings = verify.data.settings;
      const head = settings.find(s => s.key === 'codeinjection_head');
      const foot = settings.find(s => s.key === 'codeinjection_foot');
      console.log(`\n🔍 Verified:`);
      console.log(`   Header: ${head?.value?.length || 0} chars`);
      console.log(`   Footer: ${foot?.value?.length || 0} chars`);
    }
  } else {
    console.error(`❌ Failed (HTTP ${res.status}):`, JSON.stringify(res.data, null, 2));
    process.exit(1);
  }

  console.log('\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
  console.log('  ✅ Done — check https://beyondtomorrow.world');
  console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n');
}

main().catch(err => {
  console.error('Fatal error:', err);
  process.exit(1);
});
