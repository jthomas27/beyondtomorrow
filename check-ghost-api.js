const https = require('https');
const crypto = require('crypto');

// Ghost Admin API - Create About Page
// Uses session-based auth (email/password) since no API key is configured yet

const GHOST_URL = 'https://www.beyondtomorrow.world';
const ADMIN_EMAIL = 'admin@beyondtomorrow.world';

// We need the Ghost Admin API key. Let's try to create one via the admin session,
// or use Content API. First, let's check what integrations exist.

// Try fetching the site info first (public endpoint)
function fetch(url) {
  return new Promise((resolve, reject) => {
    https.get(url, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => resolve({ status: res.statusCode, data }));
    }).on('error', reject);
  });
}

async function main() {
  console.log('Checking Ghost site...');
  const res = await fetch(`${GHOST_URL}/ghost/api/admin/site/`);
  console.log('Status:', res.status);
  console.log('Response:', res.data.substring(0, 500));
}

main().catch(console.error);
