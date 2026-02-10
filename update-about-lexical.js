const https = require('https');

const GHOST_URL = 'https://www.beyondtomorrow.world';
const PAGE_ID = '698a5f33cbefc20001cbd715';

function request(method, url, body, headers) {
  return new Promise((resolve, reject) => {
    const parsed = new URL(url);
    const req = https.request({
      hostname: parsed.hostname, port: 443,
      path: parsed.pathname + parsed.search, method,
      headers: { 'Content-Type': 'application/json', Origin: GHOST_URL, Accept: 'application/json', ...headers }
    }, res => {
      let data = ''; const cookies = res.headers['set-cookie'] || [];
      res.on('data', c => data += c);
      res.on('end', () => resolve({ status: res.statusCode, data, cookies }));
    });
    req.on('error', reject);
    if (body) req.write(typeof body === 'string' ? body : JSON.stringify(body));
    req.end();
  });
}

// Build Ghost Lexical JSON from HTML content
function buildLexical(htmlContent) {
  const lexical = {
    root: {
      children: [
        {
          type: 'html',
          version: 1,
          html: htmlContent
        }
      ],
      direction: 'ltr',
      format: '',
      indent: 0,
      type: 'root',
      version: 1
    }
  };
  return JSON.stringify(lexical);
}

const htmlContent = `<p>The world is changing faster than any headline can keep up with. Artificial intelligence is rewriting the rules of entire industries overnight. Governments are racing to regulate technologies they barely understand. Supply chains, currencies, and alliances that held steady for decades are shifting beneath our feet. If you've felt like the news gives you fragments but never the full picture — that's exactly why BeyondTomorrow exists.</p>

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

<p>Subscribe to get new posts delivered straight to your inbox. No spam, no filler — just sharp thinking about where the world is headed and what it means for you.</p>`;

async function main() {
  // Login
  console.log('Logging in...');
  const login = await request('POST', GHOST_URL + '/ghost/api/admin/session/', {
    username: 'admin@beyondtomorrow.world', password: 'SilverArrows1!'
  });
  if (login.status !== 201) {
    console.error('Login failed:', login.status, login.data.substring(0, 200));
    process.exit(1);
  }
  const cookie = login.cookies.map(c => c.split(';')[0]).join('; ');
  console.log('✅ Logged in');

  // Get fresh page data
  console.log('Fetching page...');
  const pagesRes = await request('GET', GHOST_URL + '/ghost/api/admin/pages/?filter=slug:about&limit=1&formats=lexical', null, { Cookie: cookie });
  const page = JSON.parse(pagesRes.data).pages[0];
  console.log('Page ID:', page.id, '| Updated:', page.updated_at);

  // Build lexical content
  const lexicalJson = buildLexical(htmlContent);
  console.log('Lexical JSON length:', lexicalJson.length);

  // Update
  console.log('Updating page...');
  const updateRes = await request('PUT', GHOST_URL + '/ghost/api/admin/pages/' + page.id + '/', {
    pages: [{
      id: page.id,
      updated_at: page.updated_at,
      lexical: lexicalJson,
    }]
  }, { Cookie: cookie });

  if (updateRes.status === 200) {
    const updated = JSON.parse(updateRes.data).pages[0];
    console.log('✅ Page updated!');
    console.log('New HTML preview:', updated.html ? updated.html.substring(0, 150) : '(checking...)');
    console.log('🔗 https://www.beyondtomorrow.world/about/');
  } else {
    console.error('❌ Failed:', updateRes.status, updateRes.data.substring(0, 500));
  }
}

main().catch(e => { console.error(e.message); process.exit(1); });
