#!/usr/bin/env node
/**
 * Ghost Code Injection Updater
 * 
 * Pushes header.txt → Site Header and footer.txt → Site Footer
 * using the GHOST_ADMIN_API_KEY stored in Railway.
 * 
 * Usage:
 *   node inject-code.js
 *   node inject-code.js --key <id:secret>    # override with explicit key
 * 
 * Prerequisite: Run setup-ghost-api.js first to create the API key.
 */

const https = require('https');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

const GHOST_URL = 'https://www.beyondtomorrow.world';

// ── Get API key ──
function getApiKey() {
  // CLI override
  const keyIdx = process.argv.indexOf('--key');
  if (keyIdx !== -1 && process.argv[keyIdx + 1]) {
    return process.argv[keyIdx + 1];
  }

  // Environment variable
  if (process.env.GHOST_ADMIN_API_KEY) {
    return process.env.GHOST_ADMIN_API_KEY;
  }

  // Try fetching from Railway
  try {
    const output = execSync('railway variables --json 2>/dev/null', { encoding: 'utf-8' });
    const vars = JSON.parse(output);
    if (vars.GHOST_ADMIN_API_KEY) return vars.GHOST_ADMIN_API_KEY;
  } catch {}

  console.error('❌ No API key found. Set GHOST_ADMIN_API_KEY or run setup-ghost-api.js first.');
  process.exit(1);
}

// ── Generate JWT from Admin API Key ──
function makeToken(apiKey) {
  const [id, secret] = apiKey.split(':');

  // Header
  const header = Buffer.from(JSON.stringify({
    alg: 'HS256',
    typ: 'JWT',
    kid: id,
  })).toString('base64url');

  // Payload
  const now = Math.floor(Date.now() / 1000);
  const payload = Buffer.from(JSON.stringify({
    iat: now,
    exp: now + 300,
    aud: '/admin/',
  })).toString('base64url');

  // Signature
  const signature = crypto
    .createHmac('sha256', Buffer.from(secret, 'hex'))
    .update(`${header}.${payload}`)
    .digest('base64url');

  return `${header}.${payload}.${signature}`;
}

// ── HTTP helper ──
function request(method, urlPath, body, token) {
  return new Promise((resolve, reject) => {
    const url = new URL(urlPath, GHOST_URL);
    const options = {
      method,
      hostname: url.hostname,
      path: url.pathname + url.search,
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Ghost ${token}`,
      },
    };

    const req = https.request(options, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        try {
          resolve({ status: res.statusCode, data: JSON.parse(data) });
        } catch {
          resolve({ status: res.statusCode, data });
        }
      });
    });
    req.on('error', reject);
    if (body) req.write(JSON.stringify(body));
    req.end();
  });
}

// ── Main ──
async function main() {
  console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
  console.log('  Ghost Code Injection — BeyondTomorrow.World');
  console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');

  const apiKey = getApiKey();
  const token = makeToken(apiKey);
  console.log(`\n🔑 Using API key: ${apiKey.substring(0, 24)}...`);

  // Read source files (in theme/ directory)
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

  // Push to Ghost
  console.log('\n🚀 Pushing code injection...');
  const res = await request('PUT', '/ghost/api/admin/settings/', {
    settings: [
      { key: 'codeinjection_head', value: headerCode },
      { key: 'codeinjection_foot', value: footerCode },
    ]
  }, token);

  if (res.status === 200) {
    console.log('✅ Code injection updated successfully');

    // Verify
    const verify = await request('GET', '/ghost/api/admin/settings/', null, token);
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
