#!/usr/bin/env node
/**
 * Push code injection (header.txt + footer.txt) to Ghost using session auth.
 * 
 * The settings endpoint requires session cookies — JWT token auth returns 501.
 * This script logs in, pushes the code injection, then exits.
 * 
 * Usage:
 *   node push-styles.js --email admin@beyondtomorrow.world --password <password>
 */

const https = require('https');
const fs = require('fs');
const path = require('path');

const GHOST_URL = 'https://www.beyondtomorrow.world';

function parseArgs() {
  const args = process.argv.slice(2);
  const parsed = {};
  for (let i = 0; i < args.length; i += 2) {
    const key = args[i].replace(/^--/, '');
    parsed[key] = args[i + 1];
  }
  if (!parsed.email || !parsed.password) {
    console.error('Usage: node push-styles.js --email <email> --password <password>');
    process.exit(1);
  }
  return parsed;
}

function request(method, urlPath, body, headers = {}) {
  return new Promise((resolve, reject) => {
    const url = new URL(urlPath, GHOST_URL);
    const bodyStr = body ? JSON.stringify(body) : null;
    const options = {
      method,
      hostname: url.hostname,
      path: url.pathname + url.search,
      headers: {
        'Origin': GHOST_URL,
        'Content-Type': 'application/json',
        ...(bodyStr ? { 'Content-Length': Buffer.byteLength(bodyStr) } : {}),
        ...headers,
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
    if (bodyStr) req.write(bodyStr);
    req.end();
  });
}

async function main() {
  const { email, password } = parseArgs();

  console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
  console.log('  Push Code Injection — BeyondTomorrow.World');
  console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');

  // 1. Login via session auth
  console.log('\n🔐 Logging in...');
  const loginRes = await request('POST', '/ghost/api/admin/session/', {
    username: email,
    password: password,
  });

  if (loginRes.status === 403) {
    console.error('❌ Device verification required. Check email for code.');
    process.exit(1);
  }
  if (loginRes.status === 429) {
    console.error('❌ Rate limited. Run: railway redeploy --yes');
    process.exit(1);
  }
  if (loginRes.status !== 201 || !loginRes.cookies) {
    console.error(`❌ Login failed (HTTP ${loginRes.status}):`, JSON.stringify(loginRes.data, null, 2));
    process.exit(1);
  }

  const cookie = loginRes.cookies.map(c => c.split(';')[0]).join('; ');
  console.log('✅ Logged in');

  // 2. Read source files
  const headerCode = fs.readFileSync(path.join(__dirname, 'header.txt'), 'utf-8');
  const footerCode = fs.readFileSync(path.join(__dirname, 'footer.txt'), 'utf-8');
  console.log(`\n📄 Header: ${headerCode.length} chars`);
  console.log(`📄 Footer: ${footerCode.length} chars`);

  // 3. Push code injection via session auth (PUT /settings/)
  console.log('\n🚀 Pushing code injection...');
  const res = await request('PUT', '/ghost/api/admin/settings/', {
    settings: [
      { key: 'codeinjection_head', value: headerCode },
      { key: 'codeinjection_foot', value: footerCode },
    ]
  }, { Cookie: cookie });

  if (res.status === 200) {
    console.log('✅ Code injection updated successfully!');

    // Verify
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
  console.log('  ✅ Done — check https://www.beyondtomorrow.world');
  console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n');
}

main().catch(err => {
  console.error('Fatal error:', err);
  process.exit(1);
});
