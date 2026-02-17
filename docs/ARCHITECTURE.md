# BeyondTomorrow.World — Blog Plan

## What We're Building

A blog that publishes new posts automatically. Python agents (powered by Claude) research topics, write content, and publish to the blog. Agents are activated by scheduled events or incoming emails. A knowledge corpus of PDFs and emails provides context for writing.

---

## Platform Stack

| Component        | Service              | Role                                      |
|------------------|----------------------|-------------------------------------------|
| Blog             | Ghost (self-hosted)  | Displays posts, manages content           |
| Hosting          | Railway              | Runs Ghost + agent worker services        |
| Blog Database    | MySQL (Railway)      | Stores all blog content (Ghost)           |
| Vector Database  | PostgreSQL + pgvector (Railway) | Stores embeddings for AI semantic search |
| Automation       | GitHub Actions       | Triggers agent runs (schedule or event)   |
| Email            | Hostinger Business Email | Receives inbound emails (beyondtomorrow.world) |
| AI               | Claude (Anthropic)   | Powers research, writing, publishing agents |
| Embeddings       | OpenAI text-embedding-3-small | Creates vector embeddings for semantic search |
| Media Storage    | Railway Object Storage | Stores images and documents             |
| Knowledge Corpus | Railway Object Storage | Stores raw PDFs, emails, webpages       |
| Monitoring       | Railway Logs + Slack | Alerts on success/failure                 |

---

## Data Storage Strategy

Two databases serve distinct purposes, both hosted on Railway:

| Database | Purpose | Access Pattern |
|----------|---------|----------------|
| **MySQL** | Blog content (Ghost CMS) | Ghost owns all writes; agents publish via Ghost Admin API |
| **PostgreSQL + pgvector** | Knowledge embeddings for AI agents | Agents read/write directly for semantic search |

**Why two databases?**
- MySQL is required by Ghost—agents never touch it directly
- PostgreSQL with pgvector extension enables vector similarity search for the knowledge corpus
- Keeping them separate ensures Ghost stability while giving agents full control over embeddings

**How they connect:**
- Agents query the vector database to find relevant knowledge chunks before writing
- OpenAI's `text-embedding-3-small` model converts text chunks into vectors for storage and search
- Agents publish finished posts to Ghost via its Admin API (which writes to MySQL)
- Raw documents (PDFs, emails) live in Railway Object Storage; only their embeddings go to PostgreSQL

---

## How It Works

### Trigger → Agent → Review → Publish

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   TRIGGER       │ ──▶ │   AGENTS        │ ──▶ │   REVIEW        │ ──▶ │   PUBLISH       │
│                 │     │                 │     │                 │     │                 │
│ • Scheduled     │     │ • Research      │     │ • Editor Agent  │     │ Ghost Admin API │
│ • Email arrives │     │ • Summarise     │     │ • Quality check │     │       ↓         │
│                 │     │ • Write         │     │                 │     │     MySQL       │
└─────────────────┘     └─────────────────┘     └─────────────────┘     └─────────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │   KNOWLEDGE CORPUS      │
                    │                         │
                    │ • PDFs (technical docs) │
                    │ • Emails (past content) │
                    │ • Vector search index   │
                    └─────────────────────────┘
```

### Two Ways to Start a Run

1. **Scheduled (daily/weekly)**
   - GitHub Actions runs on a cron schedule
   - Calls the agent worker on Railway
   - Agent searches target websites + knowledge corpus, writes a post, publishes

2. **Email-triggered**
   - You send an email to your Hostinger business email (admin@beyondtomorrow.world)
   - Email is fetched via IMAP and processed by Railway worker
   - Railway triggers GitHub Actions
   - Agent reads the email, follows instructions, publishes
   - Email is also saved to knowledge corpus for future reference

---

## Knowledge Corpus (PDFs + Emails)

### What It Stores

| Content Type | Examples | Format |
|--------------|----------|--------|
| PDFs | Technical docs, research papers, guides | Original PDF + extracted text |
| Emails | Past instructions, topic ideas, feedback | JSON (sender, subject, body, date) |
| Web pages | Saved articles, reference material | HTML or Markdown |

### Architecture (Recommended)

```
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│  RAW STORAGE     │     │  TEXT EXTRACTION │     │  VECTOR INDEX    │
│  (Railway)       │ ──▶ │  (Python Worker) │ ──▶ │  (PostgreSQL)    │
│                  │     │                  │     │                  │
│ /pdfs/           │     │ PyPDF2 for PDFs  │     │ pgvector ext.    │
│ /emails/         │     │ JSON for emails  │     │ Semantic search  │
│ /webpages/       │     │ BeautifulSoup    │     │ Find relevant    │
└──────────────────┘     └──────────────────┘     │ chunks by topic  │
                                                  └──────────────────┘
```

### How It Works

1. **Upload** — PDFs and emails are saved to Railway Object Storage
2. **Extract** — Python worker extracts text from documents
3. **Chunk** — Text is split into smaller pieces (500-1000 words each)
4. **Embed** — OpenAI `text-embedding-3-small` creates embeddings for each chunk
5. **Index** — Embeddings are stored in PostgreSQL via pgvector
6. **Query** — Research agent searches corpus by topic before writing

### Folder Structure (R2 Bucket)

```
knowledge-corpus/
├── pdfs/
│   ├── raw/           # Original PDF files
│   └── extracted/     # Extracted text (JSON)
├── emails/
│   ├── inbound/       # Emails received via Hostinger
│   └── processed/     # Parsed and indexed
├── webpages/
│   └── saved/         # Archived web content
└── index/
    └── metadata.json  # Index of all documents
```

### Tools Required

| Tool | Purpose | Cost |
|------|---------|------|
| Railway Object Storage | Store raw files | Included in Railway plan |
| PostgreSQL + pgvector | Vector search | Included in Railway plan |
| PyPDF2 | Extract text from PDFs | Free (Python library) |
| LangChain (optional) | Simplify chunking + embedding | Free (Python library) |


---

## Agent Roles (Python + Claude)

Each agent has one job. The **Orchestrator** coordinates them.

| Agent        | Task                                             | Priority |
|--------------|--------------------------------------------------|----------|
| Orchestrator | Manages the run, calls other agents in order     | Required |
| Research     | Searches web + knowledge corpus for info         | Required |
| Summariser   | Condenses long sources into bullet points        | Required |
| Writer       | Creates the blog post (Markdown or HTML)         | Required |
| Editor       | Proofreads, improves tone, checks facts          | Required |
| Publisher    | Sends the post to Ghost via Admin API            | Required |
| Indexer      | Processes new PDFs/emails into knowledge corpus  | Required |

---

## Data Flow

1. **Trigger** — GitHub Actions starts a workflow (scheduled or via dispatch)
2. **Research** — Agent searches web + knowledge corpus
3. **Summarise** — Agent condenses sources into notes
4. **Write** — Agent creates draft post
5. **Edit** — Editor agent reviews and improves draft
6. **Publish** — Agent calls Ghost Admin API
7. **Store** — Ghost writes post to MySQL
8. **Index** — New emails saved to knowledge corpus
9. **Alert** — Success/failure notification sent
10. **Live** — Post appears on the blog

> Agents never write to MySQL directly. Ghost is the only service that touches the database.

---

## Error Handling & Retries

| Scenario | Action |
|----------|--------|
| Claude API fails | Retry 3x with exponential backoff (5s, 15s, 45s) |
| Ghost API fails | Retry 3x, then save draft locally and alert |
| Research finds nothing | Fall back to knowledge corpus only |
| PDF extraction fails | Log error, skip file, continue with others |
| pgvector search fails | Fall back to keyword search |

---

## Key Decisions (Confirmed)

| Decision                         | Choice                        |
|----------------------------------|-------------------------------|
| Where does Ghost run?            | Railway (self-hosted)         |
| Blog database                    | MySQL (Railway)               |
| Vector database                  | PostgreSQL + pgvector (Railway) |
| Where does knowledge corpus live?| Railway Object Storage        |
| Publish automatically?           | Yes (after Editor review)     |
| Image storage                    | Railway Object Storage        |
| Alerts                           | Slack webhook                 |

---

## Open Questions

1. **Email security** — Which email addresses are allowed to trigger agents?
   - *Recommendation: Start with your email only*

2. **PDF upload** — How will you add new PDFs to the corpus?
   - *Option A: Manual upload to Railway Object Storage*
   - *Option B: Email PDFs as attachments*
   - *Recommendation: Start with manual, add email later*

3. **Corpus size** — How many documents do you expect?
   - *< 100 docs: Simple keyword search is fine*
   - *100+ docs: Enable pgvector for semantic search*

---

## Estimated Costs

| Service          | Cost Driver                              | Est. Monthly |
|------------------|------------------------------------------|--------------|
| Railway          | Hosting + MySQL + PostgreSQL             | $5–25        |
| Claude API       | Tokens used per post (research + writing)| $5–50        |
| OpenAI Embeddings| Tokens for embedding corpus chunks       | $1–5         |
| Hostinger Email  | Included with domain hosting             | $0           |
| GitHub Actions   | Workflow minutes                         | Free         |
| Railway Storage  | Included in Railway hosting              | $0           |
| **Total**        |                                          | **$15–85**   |

*Start small. Costs scale with usage.*

---

## Workflow Summary

```
DAILY FLOW
──────────
1. GitHub Actions triggers at scheduled time
2. Agent worker wakes up on Railway
3. Research agent searches web + knowledge corpus
4. Summariser agent condenses findings
5. Writer agent creates draft
6. Editor agent reviews and improves
7. Publisher agent sends to Ghost
8. Ghost saves to MySQL
9. Alert sent (Slack)
10. Blog displays new post

EMAIL FLOW
──────────
1. Email sent to blog@beyondtomorrow.world
2. Railway worker fetches email via IMAP
3. Sender validated against allowlist
4. Email saved to knowledge corpus
5. Agent reads email, follows instructions
6. Same flow as above (research → publish)
7. Reply email sent with post link

CORPUS UPDATE FLOW
──────────────────
1. New PDF uploaded to Railway Object Storage (manual or via email)
2. Indexer agent detects new file
3. Text extracted from PDF
4. Text chunked into smaller pieces
5. Embeddings created via OpenAI `text-embedding-3-small`
6. Chunks indexed in PostgreSQL (pgvector)
7. Document available for future research
```

---

## Security

### Infrastructure Security (Cloudflare + Railway)

| Layer | Measure | Status |
|-------|---------|--------|
| **DNS/Proxy** | Cloudflare (free tier) proxies all traffic — hides Railway origin IP | ✅ Active |
| **SSL/TLS** | Cloudflare Full (Strict) mode + Railway auto-provisioned Let's Encrypt cert | ✅ Active |
| **HSTS** | `max-age=15552000; includeSubDomains; preload` (180 days) | ✅ Active |
| **HTTP → HTTPS** | Cloudflare "Always Use HTTPS" — 301 redirect on all HTTP requests | ✅ Active |
| **Minimum TLS** | TLS 1.2 minimum enforced at Cloudflare edge | ✅ Active |
| **DDoS** | Cloudflare automatic DDoS mitigation | ✅ Active |
| **Domain routing** | Primary domain: `beyondtomorrow.world` — www 301-redirects to root | ✅ Active |
| **Database access** | MySQL and pgvector use Railway internal networking only — no public proxies | ✅ Active |

### Application Security (Ghost Code Injection)

Security headers are injected via Ghost's site-wide code injection (managed by `scripts/inject-code.js`):

| Header | Value | Purpose |
|--------|-------|---------|
| `Content-Security-Policy` | Restrictive CSP allowing only trusted sources | Prevents XSS and code injection |
| `X-Content-Type-Options` | `nosniff` | Prevents MIME-type sniffing |
| `X-Frame-Options` | `SAMEORIGIN` | Prevents clickjacking |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | Controls referrer leakage |
| `Permissions-Policy` | Denies camera, microphone, geolocation, payment | Blocks unnecessary browser APIs |

Additional client-side protections (via footer code injection):
- `<meta name="generator">` tag removed from DOM (hides Ghost version)
- Ghost social meta tags removed from DOM

### Cloudflare Security Rules

| Rule | Target | Action |
|------|--------|--------|
| **Rate limit Ghost admin login** | `/ghost/api/admin/session/` | Block after 5 req/10s per IP (60s ban) |
| **Rate limit magic link** | `/members/api/send-magic-link/` | Block after 3 req/min per IP (300s ban) |
| **Remove X-Powered-By** | All responses | Transform rule strips `X-Powered-By: Express` header |
| **Redirect www to root** | `www.beyondtomorrow.world` | 301 redirect to `beyondtomorrow.world` |

### Cloudflare DNS Records

| Type | Name | Content | Proxy |
|------|------|---------|-------|
| CNAME | @ | `ghost-production-66d4.up.railway.app` | Proxied (orange) |
| CNAME | www | `ghost-production-66d4.up.railway.app` | Proxied (orange) |
| CNAME | autoconfig | `autoconfig.mail.hostinger.c...` | DNS only |
| CNAME | autodiscover | `autodiscover.mail.hostinge...` | DNS only |
| CNAME | hostingermail-a/b/c | DKIM records | DNS only |
| MX | @ | `mx1.hostinger.com` (5), `mx2.hostinger.com` (10) | DNS only |
| TXT | @ | SPF record | DNS only |
| TXT | _dmarc | `v=DMARC1; p=none` | DNS only |
| CAA | @ | Multiple CA issuers (DigiCert, Let's Encrypt, etc.) | DNS only |

> ⚠️ Email CNAMEs (autoconfig, autodiscover, hostingermail-*) MUST stay DNS-only or Hostinger email will break.

### Security Best Practices

- Store API keys in Railway environment variables (not in code)
- Only accept emails from an allowlist of senders
- Log all agent actions for debugging
- Use rate limits on external API calls
- Validate file types before processing (PDFs only)
- Ghost Admin API settings changes require session auth (email/password), not API keys
- Use `scripts/inject-code.js` to push security header updates to Ghost

---

## Next Steps

1. ~~Set up Railway project with Ghost + MySQL~~ ✅ Done
2. ~~Add PostgreSQL service with pgvector extension~~ ✅ Done
3. Create GitHub repo with Actions workflow
4. Configure Hostinger email IMAP settings for Railway
5. Set up Railway Object Storage bucket
6. Build Indexer agent (process PDFs)
7. Build Orchestrator agent
8. Build Research agent (web + corpus search)
9. Build Writer + Editor agents
10. Build Publisher agent (needs Ghost Admin API key)
11. Set up Slack alerts
12. Upload initial PDFs to corpus
13. Test end-to-end with scheduled run
