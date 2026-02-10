const https = require('https');
const http = require('http');
const readline = require('readline');

const GHOST_URL = 'https://www.beyondtomorrow.world';

function request(method, url, body = null, headers = {}) {
  return new Promise((resolve, reject) => {
    const parsed = new URL(url);
    const options = {
      hostname: parsed.hostname,
      port: parsed.port || 443,
      path: parsed.pathname + parsed.search,
      method,
      headers: {
        'Content-Type': 'application/json',
        'Origin': GHOST_URL,
        'Accept': 'application/json',
        ...headers,
      },
    };

    const req = https.request(options, (res) => {
      let data = '';
      const cookies = res.headers['set-cookie'] || [];
      res.on('data', chunk => data += chunk);
      res.on('end', () => resolve({ status: res.statusCode, data, cookies, headers: res.headers }));
    });

    req.on('error', reject);
    if (body) req.write(JSON.stringify(body));
    req.end();
  });
}

function askQuestion(query) {
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  return new Promise(resolve => rl.question(query, ans => { rl.close(); resolve(ans.trim()); }));
}

async function main() {
  // Step 1: Create a session (login)
  console.log('[1/3] Logging in to Ghost Admin...');
  const loginRes = await request('POST', `${GHOST_URL}/ghost/api/admin/session/`, {
    username: 'admin@beyondtomorrow.world',
    password: 'SilverArrows1!'
  });

  // Extract session cookie from any response (needed for 2FA verify too)
  const sessionCookie = loginRes.cookies
    .map(c => c.split(';')[0])
    .join('; ');

  // Handle 2FA / device verification
  if (loginRes.status === 403) {
    console.log('  🔐 Device verification required — check admin@beyondtomorrow.world for the auth code.');
    const code = await askQuestion('  Enter verification code: ');

    const verifyRes = await request('PUT', `${GHOST_URL}/ghost/api/admin/session/verify/`, {
      token: code
    }, { Cookie: sessionCookie });

    if (verifyRes.status !== 200 && verifyRes.status !== 201) {
      console.error('  ❌ Verification failed:', verifyRes.status, verifyRes.data.substring(0, 300));
      process.exit(1);
    }
    console.log('  ✅ Verified and logged in successfully');
  } else if (loginRes.status === 201 || loginRes.status === 200) {
    console.log('  ✅ Logged in successfully');
  } else {
    console.error('Login failed:', loginRes.status, loginRes.data.substring(0, 300));
    process.exit(1);
  }

  // Step 2: Check if About page already exists
  console.log('[2/3] Checking for existing About page...');
  const pagesRes = await request('GET', `${GHOST_URL}/ghost/api/admin/pages/?filter=slug:about&limit=1`, null, {
    Cookie: sessionCookie,
  });

  if (pagesRes.status === 200) {
    const pagesData = JSON.parse(pagesRes.data);
    if (pagesData.pages && pagesData.pages.length > 0) {
      console.log('  ⚠️  About page already exists:', pagesData.pages[0].title);
      console.log('  URL:', pagesData.pages[0].url);
      console.log('  Updating existing page...');
      
      const existingPage = pagesData.pages[0];
      
      // Ghost stores content as mobiledoc internally. To update via html,
      // we must use the lexical editor format or clear mobiledoc.
      // The correct approach is to send lexical content with source: 'html'
      const updateRes = await request('PUT', `${GHOST_URL}/ghost/api/admin/pages/${existingPage.id}/?source=html`, {
        pages: [{
          id: existingPage.id,
          updated_at: existingPage.updated_at,
          title: 'About',
          slug: 'about',
          status: 'published',
          lexical: getAboutPageHTML(),
          mobiledoc: null,
          custom_excerpt: 'What is BeyondTomorrow.World? An AI-powered blog exploring the forces shaping our future — technology, geopolitics, and economics.',
          feature_image: existingPage.feature_image || null,
          meta_title: 'About — BeyondTomorrow.World',
          meta_description: 'An AI-powered blog exploring how technology, geopolitics, and economics are shaping the world of tomorrow.',
          og_title: 'About — BeyondTomorrow.World',
          og_description: 'An AI-powered blog exploring the forces shaping our future.',
          twitter_title: 'About — BeyondTomorrow.World',
          twitter_description: 'An AI-powered blog exploring the forces shaping our future.',
        }]
      }, { Cookie: sessionCookie });

      if (updateRes.status === 200) {
        console.log('  ✅ About page updated!');
        console.log(`  🔗 ${GHOST_URL}/about/`);
      } else {
        console.error('  ❌ Update failed:', updateRes.status, updateRes.data.substring(0, 500));
        
        // If lexical with source=html failed, try mobiledoc approach
        console.log('  Retrying with mobiledoc format...');
        // Re-fetch to get fresh updated_at
        const freshRes = await request('GET', `${GHOST_URL}/ghost/api/admin/pages/?filter=slug:about&limit=1`, null, { Cookie: sessionCookie });
        const freshData = JSON.parse(freshRes.data);
        const freshPage = freshData.pages[0];
        
        const mobiledocContent = buildMobiledoc(getAboutPageHTML());
        const retryRes = await request('PUT', `${GHOST_URL}/ghost/api/admin/pages/${freshPage.id}/`, {
          pages: [{
            id: freshPage.id,
            updated_at: freshPage.updated_at,
            mobiledoc: mobiledocContent,
          }]
        }, { Cookie: sessionCookie });
        
        if (retryRes.status === 200) {
          console.log('  ✅ About page updated (mobiledoc)!');
          console.log(`  🔗 ${GHOST_URL}/about/`);
        } else {
          console.error('  ❌ Retry also failed:', retryRes.status, retryRes.data.substring(0, 500));
        }
      }
      return;
    }
  }

  // Step 3: Create the About page
  console.log('[3/3] Creating About page...');
  const createRes = await request('POST', `${GHOST_URL}/ghost/api/admin/pages/`, {
    pages: [{
      title: 'About',
      slug: 'about',
      status: 'published',
      html: getAboutPageHTML(),
      custom_excerpt: 'What is BeyondTomorrow.World? An AI-powered blog exploring the forces shaping our future — technology, geopolitics, and economics.',
      meta_title: 'About — BeyondTomorrow.World',
      meta_description: 'An AI-powered blog exploring how technology, geopolitics, and economics are shaping the world of tomorrow.',
      og_title: 'About — BeyondTomorrow.World',
      og_description: 'An AI-powered blog exploring the forces shaping our future.',
      twitter_title: 'About — BeyondTomorrow.World',
      twitter_description: 'An AI-powered blog exploring the forces shaping our future.',
    }]
  }, { Cookie: sessionCookie });

  if (createRes.status === 201 || createRes.status === 200) {
    const page = JSON.parse(createRes.data);
    console.log('  ✅ About page created!');
    console.log(`  🔗 ${GHOST_URL}/about/`);
    if (page.pages && page.pages[0]) {
      console.log(`  ID: ${page.pages[0].id}`);
    }
  } else {
    console.error('  ❌ Create failed:', createRes.status, createRes.data.substring(0, 500));
  }
}

function buildMobiledoc(html) {
  // Ghost mobiledoc format with an HTML card containing all our content
  return JSON.stringify({
    version: '0.3.1',
    atoms: [],
    cards: [['html', { html: html }]],
    markups: [],
    sections: [[10, 0]]
  });
}

function getAboutPageHTML() {
  return `
<p>The world is changing faster than any headline can keep up with. Artificial intelligence is rewriting the rules of entire industries overnight. Governments are racing to regulate technologies they barely understand. Supply chains, currencies, and alliances that held steady for decades are shifting beneath our feet. If you've felt like the news gives you fragments but never the full picture — that's exactly why BeyondTomorrow exists.</p>

<h2>What We Cover</h2>

<p>BeyondTomorrow.World sits at the intersection of four forces that are actively reshaping civilisation:</p>

<p><strong>Artificial Intelligence</strong> — not just the product launches and stock prices, but what happens when AI enters healthcare, law, warfare, education, and creative work. We look at the capabilities, the limitations, and the second-order effects that most coverage ignores.</p>

<p><strong>Technology</strong> — the breakthroughs in computing, energy, biotech, and infrastructure that will define the next decade. We cut through the noise to focus on what actually matters and why.</p>

<p><strong>Geopolitics</strong> — the power plays between nations, the trade wars, the shifting alliances, and the conflicts that redraw borders and rewrite rules. Technology doesn't exist in a vacuum — it's shaped by politics, and politics is increasingly shaped by technology.</p>

<p><strong>Economics</strong> — the policies, markets, and structural forces that determine who prospers and who gets left behind. From central bank decisions to the economics of AI adoption, we connect the dots between money, power, and the future of work.</p>

<h2>How This Blog Works</h2>

<p>Here's where it gets interesting. Every article on BeyondTomorrow is researched, written, edited, and published by AI agents — not by a human writer sitting at a keyboard. This isn't auto-generated filler or recycled press releases. It's a structured pipeline where specialised agents each handle a distinct stage of the process.</p>

<p>First, a research agent scans the web and searches a curated knowledge corpus — a private collection of PDFs, reports, academic papers, and reference material that gives the AI context no generic model has access to. Then a writing agent drafts the article, grounded in what the research actually found. A separate editing agent reviews the draft for clarity, accuracy, and tone. Only then does the finished piece go live.</p>

<p>The result is writing that's informed, specific, and grounded in real sources — produced at a pace and consistency that a solo human operation simply can't match. Think of it as a newsroom where every desk is staffed by a purpose-built AI, each one focused on doing its job well.</p>

<h2>Who This Is For</h2>

<p>If you're the kind of person who reads past the headline, who wants to understand <em>why</em> something is happening and not just <em>what</em> — this blog is for you. Whether you work in tech, follow global affairs, invest, or simply want to make sense of a world that's moving fast, BeyondTomorrow is designed to be clear, direct, and worth your time. No jargon walls. No hype cycles. No fluff.</p>

<h2>Built in the Open</h2>

<p>BeyondTomorrow runs on <a href="https://ghost.org">Ghost</a>, hosted on <a href="https://railway.app">Railway</a>, with the full agent pipeline powered by <a href="https://anthropic.com">Claude</a>. The entire project is open source — you can see exactly how it works, fork it, or build your own version on <a href="https://github.com/jthomas27/beyondtomorrow">GitHub</a>.</p>

<h2>Stay Ahead</h2>

<p>Subscribe to get new posts delivered straight to your inbox. No spam, no filler — just sharp thinking about where the world is headed and what it means for you.</p>
`.trim();
}

main().catch(err => {
  console.error('Error:', err.message);
  process.exit(1);
});
