#!/usr/bin/env node
/**
 * Ghost Admin API Setup & Code Injection Updater
 * 
 * 1. Logs in via session auth (one-time)
 * 2. Creates a "Publisher Agent" custom integration → gets an Admin API Key
 * 3. Saves the key to Railway env vars
 * 4. Uses the key to push header.txt + footer.txt into Ghost Code Injection
 * 
 * Usage:
 *   node setup-ghost-api.js --email admin@beyondtomorrow.world
 *   GHOST_ADMIN_EMAIL=<email> GHOST_ADMIN_PASSWORD=<password> node setup-ghost-api.js
 *   printf '%s' '<password>' | node setup-ghost-api.js --email admin@beyondtomorrow.world --password-stdin
 * 
 * After first run, the API key is stored in Railway. Future code injection
 * updates can use:  node inject-code.js
 */

const https = require('https');
const fs = require('fs');
const path = require('path');
const readline = require('readline');
const { spawnSync } = require('child_process');

const GHOST_URL = 'https://beyondtomorrow.world';
const INTEGRATION_NAME = 'Publisher Agent';

// ── Parse CLI args ──
function parseArgs() {
  const args = process.argv.slice(2);
  const parsed = {};
  for (let i = 0; i < args.length; i += 1) {
    const key = args[i].replace(/^--/, '');
    if (key === 'password-stdin') {
      parsed[key] = true;
      continue;
    }

    parsed[key] = args[i + 1];
    i += 1;
  }
  if (parsed.password) {
    console.error('Passing --password on the command line is disabled. Use GHOST_ADMIN_PASSWORD, --password-stdin, or the interactive prompt.');
    process.exit(1);
  }
  return parsed;
}

function promptLine(promptText) {
  return new Promise((resolve) => {
    const rl = readline.createInterface({
      input: process.stdin,
      output: process.stdout,
    });

    rl.question(promptText, (answer) => {
      rl.close();
      resolve(answer.trim());
    });
  });
}

function promptHidden(promptText) {
  return new Promise((resolve, reject) => {
    if (!process.stdin.isTTY) {
      reject(new Error('Hidden password prompt requires a TTY. Use GHOST_ADMIN_PASSWORD or --password-stdin.'));
      return;
    }

    const stdin = process.stdin;
    let value = '';

    function cleanup() {
      stdin.setRawMode(false);
      stdin.pause();
      stdin.removeListener('data', onData);
    }

    function onData(chunk) {
      const char = String(chunk);

      if (char === '\u0003') {
        cleanup();
        reject(new Error('Input cancelled.'));
        return;
      }

      if (char === '\r' || char === '\n') {
        process.stdout.write('\n');
        cleanup();
        resolve(value.trim());
        return;
      }

      if (char === '\u007f') {
        value = value.slice(0, -1);
        return;
      }

      value += char;
    }

    process.stdout.write(promptText);
    stdin.resume();
    stdin.setRawMode(true);
    stdin.setEncoding('utf8');
    stdin.on('data', onData);
  });
}

function readPasswordFromStdin() {
  return new Promise((resolve, reject) => {
    if (process.stdin.isTTY) {
      resolve('');
      return;
    }

    let data = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', (chunk) => {
      data += chunk;
    });
    process.stdin.on('end', () => resolve(data.trim()));
    process.stdin.on('error', reject);
  });
}

async function resolveCredentials(parsed) {
  const email = parsed.email || process.env.GHOST_ADMIN_EMAIL || await promptLine('Ghost admin email: ');

  let password = process.env.GHOST_ADMIN_PASSWORD || '';
  if (!password && parsed['password-stdin']) {
    password = await readPasswordFromStdin();
  }
  if (!password) {
    password = await promptHidden('Ghost admin password: ');
  }

  if (!email || !password) {
    console.error('Ghost admin credentials are required. Provide GHOST_ADMIN_EMAIL and GHOST_ADMIN_PASSWORD, use --password-stdin, or answer the prompts.');
    process.exit(1);
  }

  return { email, password };
}

function ensureRailwayCli() {
  const versionCheck = spawnSync('railway', ['--version'], { encoding: 'utf8' });
  if (versionCheck.error || versionCheck.status !== 0) {
    console.error('Railway CLI is required before creating or rotating the Ghost Admin API key. Install it and run `railway login`, then retry.');
    process.exit(1);
  }

  const loginCheck = spawnSync('railway', ['whoami'], { encoding: 'utf8' });
  if (loginCheck.error || loginCheck.status !== 0) {
    console.error('Railway CLI is not authenticated. Run `railway login`, then retry.');
    process.exit(1);
  }
}

// ── HTTP helper ──
function request(method, urlPath, body, headers = {}) {
  return new Promise((resolve, reject) => {
    const url = new URL(urlPath, GHOST_URL);
    const options = {
      method,
      hostname: url.hostname,
      path: url.pathname + url.search,
      headers: {
        'Origin': GHOST_URL,
        'Content-Type': 'application/json',
        ...headers,
      },
    };

    const req = https.request(options, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        const cookies = res.headers['set-cookie'];
        try {
          resolve({ status: res.statusCode, data: data ? JSON.parse(data) : null, cookies, headers: res.headers });
        } catch {
          resolve({ status: res.statusCode, data: data, cookies, headers: res.headers });
        }
      });
    });
    req.on('error', reject);
    if (body) req.write(JSON.stringify(body));
    req.end();
  });
}

// ── Step 1: Session login ──
async function login(email, password) {
  console.log('\n🔐 Step 1: Logging in via session auth...');
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
    console.error('   ❌ 403 — Device verification required.');
    console.error('   Check your email for a verification code, then retry after approving the device.');
    process.exit(1);
  }

  if (res.status === 429) {
    console.error('   ❌ 429 — Rate limited. Wait a few minutes and try again, or redeploy Ghost:');
    console.error('   railway redeploy --yes');
    process.exit(1);
  }

  console.error(`   ❌ Login failed (HTTP ${res.status}):`, JSON.stringify(res.data, null, 2));
  process.exit(1);
}

// ── Step 2: Check for existing integration ──
async function findIntegration(cookie) {
  console.log('\n🔍 Step 2: Checking for existing integration...');
  const res = await request('GET', '/ghost/api/admin/integrations/?include=api_keys&limit=all', null, { Cookie: cookie });

  if (res.status !== 200) {
    console.error('   ❌ Failed to list integrations:', res.status);
    return null;
  }

  const existing = res.data.integrations.find(i => i.name === INTEGRATION_NAME);
  if (existing) {
    const adminKey = existing.api_keys.find(k => k.type === 'admin');
    if (adminKey) {
      console.log(`   ✅ Found existing "${INTEGRATION_NAME}" integration`);
      console.log(`   Key ID: ${adminKey.id}`);
      return adminKey.secret ? `${adminKey.id}:${adminKey.secret}` : null;
    }
  }

  console.log(`   ℹ️  No existing "${INTEGRATION_NAME}" integration found`);
  return null;
}

// ── Step 3: Create integration ──
async function createIntegration(cookie) {
  console.log('\n🔧 Step 3: Creating custom integration...');
  const res = await request('POST', '/ghost/api/admin/integrations/', {
    integrations: [{
      name: INTEGRATION_NAME,
      description: 'Admin API key for automated publishing and code injection updates',
    }]
  }, { Cookie: cookie });

  if (res.status === 201 || res.status === 200) {
    const integration = res.data.integrations[0];
    const adminKey = integration.api_keys.find(k => k.type === 'admin');
    const apiKey = `${adminKey.id}:${adminKey.secret}`;
    console.log(`   ✅ Integration created: "${INTEGRATION_NAME}"`);
    return apiKey;
  }

  console.error(`   ❌ Failed to create integration (HTTP ${res.status}):`, JSON.stringify(res.data, null, 2));
  process.exit(1);
}

// ── Step 4: Save to Railway ──
function saveToRailway(apiKey) {
  console.log('\n💾 Step 4: Saving API key to Railway...');
  const result = spawnSync('railway', ['variables', '--set', `GHOST_ADMIN_API_KEY=${apiKey}`], {
    stdio: ['ignore', 'pipe', 'pipe'],
    cwd: process.cwd(),
    encoding: 'utf8',
  });

  if (result.error || result.status !== 0) {
    console.error('   Failed to save GHOST_ADMIN_API_KEY to Railway. The key was not printed for safety. Resolve the Railway CLI issue and re-run the setup script to rotate the key if needed.');
    process.exit(1);
  }

  console.log('   ✅ GHOST_ADMIN_API_KEY saved to Railway environment');
}

// ── Step 5: Push code injection ──
async function pushCodeInjection(cookie) {
  console.log('\n🎨 Step 5: Pushing code injection from header.txt + footer.txt...');

  // Read local source files
  const headerPath = path.join(__dirname, '..', 'theme', 'header.txt');
  const footerPath = path.join(__dirname, '..', 'theme', 'footer.txt');

  if (!fs.existsSync(headerPath)) {
    console.error('   ❌ header.txt not found');
    process.exit(1);
  }

  const headerCode = fs.readFileSync(headerPath, 'utf-8');
  const footerCode = fs.existsSync(footerPath) ? fs.readFileSync(footerPath, 'utf-8') : '';

  // Get current settings to preserve other values
  const getRes = await request('GET', '/ghost/api/admin/settings/', null, { Cookie: cookie });
  if (getRes.status !== 200) {
    console.error('   ❌ Failed to fetch settings:', getRes.status);
    process.exit(1);
  }

  // Update code injection
  const res = await request('PUT', '/ghost/api/admin/settings/', {
    settings: [
      { key: 'codeinjection_head', value: headerCode },
      { key: 'codeinjection_foot', value: footerCode },
    ]
  }, { Cookie: cookie });

  if (res.status === 200) {
    console.log(`   ✅ Code injection updated`);
    console.log(`   Header: ${headerCode.length} chars from header.txt`);
    console.log(`   Footer: ${footerCode.length} chars from footer.txt`);
  } else {
    console.error(`   ❌ Failed to update code injection (HTTP ${res.status}):`, JSON.stringify(res.data, null, 2));
  }
}

// ── Main ──
async function main() {
  ensureRailwayCli();

  const parsed = parseArgs();
  const { email, password } = await resolveCredentials(parsed);

  console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
  console.log('  Ghost Admin API Setup — BeyondTomorrow.World');
  console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');

  // 1. Login
  const cookie = await login(email, password);

  // 2. Check for existing key
  let apiKey = await findIntegration(cookie);

  // 3. Create if not found
  if (!apiKey) {
    apiKey = await createIntegration(cookie);
  }

  // 4. Save key to Railway
  if (apiKey) {
    saveToRailway(apiKey);
  }

  // 5. Push code injection
  await pushCodeInjection(cookie);

  console.log('\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
  console.log('  ✅ Setup complete');
  console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
  console.log('\nFuture code injection updates:');
  console.log('  node scripts/inject-code.js');
  console.log('');
}

main().catch(err => {
  console.error('Fatal error:', err);
  process.exit(1);
});
