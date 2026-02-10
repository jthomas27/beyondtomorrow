# BeyondTomorrow.World

> A blog exploring ideas that shape our future — written, reviewed, and published entirely by AI.

[![Deploy on Railway](https://railway.com/button.svg)](https://railway.app)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

---

## What Is This?

BeyondTomorrow is a self-running blog. AI agents handle the entire process — from finding topics to publishing finished articles. You provide the direction; the system does the rest.

**What it does:**

- 📝 **Writes blog posts automatically** — AI agents research, draft, edit, and publish
- 🔍 **Learns from your documents** — upload PDFs, emails, or web pages to inform the writing
- ⏱️ **Runs on a schedule** — new posts appear daily or weekly without manual effort
- 📧 **Accepts email commands** — send an email to trigger a post on a specific topic

---

## How It Works

The system follows a simple pipeline. Each step is handled by a dedicated AI agent.

```
  Schedule / Email
        │
        ▼
   ┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐
   │ Research  │ ──▶ │  Write   │ ──▶ │  Review  │ ──▶ │ Publish  │
   └──────────┘     └──────────┘     └──────────┘     └──────────┘
        │                                                    │
        ▼                                                    ▼
   ┌──────────┐                                     ┌──────────────┐
   │ Knowledge│                                     │ Live on Blog │
   │  Corpus  │                                     │              │
   └──────────┘                                     └──────────────┘
```

### Step by Step

| Step | What Happens |
|------|-------------|
| **1. Trigger** | A scheduled timer fires, or you send an email |
| **2. Research** | The AI searches the web and your uploaded documents for relevant info |
| **3. Summarise** | Key findings are condensed into notes |
| **4. Write** | A draft blog post is created |
| **5. Edit** | A separate AI agent reviews for quality, tone, and accuracy |
| **6. Publish** | The finished post goes live on the blog |
| **7. Notify** | You receive a success or failure alert |

### Knowledge Corpus

The AI doesn't just search the web — it also reads **your own documents** for context. This uses a technique called *Retrieval-Augmented Generation (RAG)*:

1. You upload files (PDFs, emails, web pages) to storage
2. The system extracts and indexes the text
3. Before writing, agents search these documents for relevant information
4. Posts are more accurate because they draw on your source material

> 📖 Full details in [docs/RAG_WORKFLOW.md](docs/RAG_WORKFLOW.md)

---

## Getting Started

### What You'll Need

| Requirement | Why |
|-------------|-----|
| [Railway](https://railway.app) account | Hosts the blog and all services |
| [GitHub](https://github.com) account | Stores code and runs scheduled tasks |
| Domain name | Your blog's web address (e.g. beyondtomorrow.world) |
| Claude API key | Powers the AI writing ([anthropic.com](https://anthropic.com)) |
| OpenAI API key | Powers document search ([openai.com](https://openai.com)) |
| Hostinger email *(optional)* | Lets you trigger posts via email |

### Quick Start

**1. Clone this repository**
```bash
git clone https://github.com/jthomas27/beyondtomorrow.git
cd beyondtomorrow
```

**2. Deploy to Railway**
- Log in to [railway.app](https://railway.app)
- Click **New Project** → **Deploy from GitHub repo**
- Select this repository — Railway handles the rest

**3. Add services in Railway**

| Service | What It Does |
|---------|-------------|
| Ghost | The blog platform (displays your posts) |
| MySQL | Stores blog content |
| PostgreSQL | Stores document embeddings for AI search |
| Object Storage | Holds uploaded PDFs, images, and media |

**4. Set environment variables**

Add these in Railway's dashboard under **Variables**:

| Variable | Value |
|----------|-------|
| `GHOST_URL` | `https://beyondtomorrow.world` |
| `DATABASE_CLIENT` | `mysql` |
| `CLAUDE_API_KEY` | Your Anthropic API key |
| `OPENAI_API_KEY` | Your OpenAI API key |

**5. Connect your domain**
- Go to Railway → **Settings** → **Domains**
- Add `beyondtomorrow.world`
- Update your DNS records at your registrar (instructions provided by Railway)
- SSL is set up automatically

> 🚀 Full walkthrough in [docs/DEPLOYMENT_PLAN.md](docs/DEPLOYMENT_PLAN.md)

---

## Project Structure

```
BeyondTomorrow.World/
├── README.md                 # This file
├── package.json              # Dependencies & npm scripts
│
├── docs/                     # Documentation
│   ├── ARCHITECTURE.md       # System design — services, databases, agents
│   ├── DEPLOYMENT_PLAN.md    # Step-by-step Railway deployment guide
│   ├── GHOST_PUBLISHING_GUIDE.md  # Ghost Admin API reference
│   ├── POSTGRES_SETUP_GUIDE.md    # pgvector setup on Railway
│   ├── RAG_WORKFLOW.md       # How AI reads and learns from documents
│   └── SMTP_ISSUE.md         # SMTP troubleshooting log (historical)
│
├── theme/                    # Ghost Code Injection source files
│   ├── header.txt            # CSS → injected into Site Header
│   └── footer.txt            # JS  → injected into Site Footer
│
├── scripts/                  # Utility & maintenance scripts
│   ├── inject-code.js        # Push theme to Ghost (reusable)
│   ├── setup-ghost-api.js    # One-time API key setup
│   ├── db-test.js            # PostgreSQL / pgvector connectivity
│   ├── mysql-test.js         # MySQL diagnostic
│   └── fix-migration-lock.js # Emergency migration lock release
│
└── assets/                   # Static assets
    └── images/               # Feature images for blog posts
```

### npm Scripts

| Command | Description |
|---------|-------------|
| `npm run ghost:inject` | Push theme CSS/JS to Ghost |
| `npm run ghost:setup` | One-time Ghost API key setup |
| `npm run db:test` | Test PostgreSQL connection |
| `npm run db:connect` | Test via Railway (`railway run`) |
| `npm run mysql:test` | Test MySQL connection |
| `npm run mysql:fix-lock` | Fix stuck Ghost migration lock |

### Documentation

| Document | What's Inside |
|----------|---------------|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Full system design — services, databases, agents, data flow |
| [docs/DEPLOYMENT_PLAN.md](docs/DEPLOYMENT_PLAN.md) | Step-by-step deployment and domain setup guide |
| [docs/GHOST_PUBLISHING_GUIDE.md](docs/GHOST_PUBLISHING_GUIDE.md) | Ghost Admin API — auth, Lexical format, publishing |
| [docs/POSTGRES_SETUP_GUIDE.md](docs/POSTGRES_SETUP_GUIDE.md) | pgvector setup, table schema, pgAdmin |
| [docs/RAG_WORKFLOW.md](docs/RAG_WORKFLOW.md) | How the AI reads and learns from your documents |

---

## Services & Costs

All services run on [Railway](https://railway.app). Costs depend on how often posts are published.

| Service | Role | Est. Monthly Cost |
|---------|------|-------------------|
| Railway | Hosting, databases, storage | $5 – $25 |
| Claude API | AI writing and editing | $5 – $50 |
| OpenAI API | Document search | $1 – $5 |
| Hostinger Email | Email triggers | Included with domain |
| GitHub Actions | Scheduled automation | Free |
| **Total** | | **$11 – $85** |

> 💡 Start small. You can scale up as the blog grows.

---

## Security

| Measure | Detail |
|---------|--------|
| **API keys** | Stored securely in Railway environment variables — never in code |
| **Email triggers** | Only emails from approved senders are accepted |
| **Logging** | All AI agent actions are recorded for review |
| **Rate limiting** | External API calls are throttled to prevent misuse |
| **File validation** | Only approved file types (e.g. PDF) are processed |

---

## License

This project is licensed under the [MIT License](LICENSE).
