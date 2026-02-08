# BeyondTomorrow.World - Deployment Plan

Deployment guide for the BeyondTomorrow.World blog platform on Railway, powered by Ghost CMS.

**Project:** caring-alignment
**Domain:** beyondtomorrow.world
**Railway Project ID:** 752fdaea-fd96-4521-bec6-b7d5ef451270

---

## Railway Services Overview

> **Status:** ✅ All services deployed and verified.

| Service | Type | Role | Service ID |
|---------|------|------|------------|
| **ghost** | Ghost CMS (Docker `ghost:5`) | Blog front-end + CMS admin | `0daf496c-e14f-41d4-b89b-3624a778c99d` |
| **MySQL** | MySQL 9.4 database | Blog content storage (Ghost) | `375d48d7-df84-4acc-a93b-9fc69159a44e` |
| **pgvector** | PostgreSQL 18 + pgvector | AI knowledge embeddings | `2a98f138-d230-4633-87ad-729736bfbc92` |

---

## Part 1: Ghost CMS Setup

### Ghost Service
Deployed as a Docker image (`ghost:5`) on Railway with:
- Persistent volume at `/var/lib/ghost/content` for themes, images, and uploads
- Connected to MySQL via Railway's internal network
- Custom domain: `beyondtomorrow.world`
- Railway domain: `ghost-production-66d4.up.railway.app`
- Admin panel: `https://beyondtomorrow.world/ghost/`

### MySQL Service
Railway-managed MySQL 9.4 with:
- Persistent volume at `/var/lib/mysql`
- Internal host: `mysql.railway.internal:3306`
- Public proxy: `metro.proxy.rlwy.net:32958`
- Database: `railway`
- Ghost tables: 58 tables auto-created on first boot

### pgvector Service
PostgreSQL 18 with pgvector extension:
- Persistent volume at `/var/lib/postgresql`
- Internal host: `pgvector.railway.internal:5432`
- Public proxy: `ballast.proxy.rlwy.net:32490`
- 5 tables: documents, chunks, embeddings, blog_posts, knowledge_graph
- See [POSTGRES_SETUP_GUIDE.md](POSTGRES_SETUP_GUIDE.md) for details

---

## Part 2: Ghost Environment Variables

```
url                            = https://beyondtomorrow.world
database__client               = mysql
database__connection__host     = mysql.railway.internal
database__connection__port     = 3306
database__connection__user     = root
database__connection__database = railway
NODE_ENV                       = production
PORT                           = 2368
mail__transport                = Direct
mail__from                     = noreply@beyondtomorrow.world
privacy__useUpdateCheck        = false
privacy__useGravatar           = false
privacy__useRpcPing            = false
privacy__useStructuredData     = true
```

---

## Part 3: GitHub Repository

**Repository:** https://github.com/jthomas27/beyondtomorrow.git

The repo contains utility scripts and documentation:
- `db-test.js` — pgvector connectivity test and table creation
- `mysql-test.js` — MySQL connectivity test and Ghost table verification
- `fix-migration-lock.js` — Utility to clear Ghost migration locks

---

## Part 4: Custom Domain (beyondtomorrow.world)

> **Status:** ✅ Domain assigned to Ghost service and verified.

### DNS Records Required

Configure these at your domain registrar:

| Purpose | Type | Name | Value |
|---------|------|------|-------|
| Root domain | CNAME | @ | `mj7rnb3d.up.railway.app` |
| WWW subdomain | CNAME | www | `t0qibbne.up.railway.app` |

> ⚠️ Some registrars don't allow CNAME on root domain. Use Cloudflare (free) for CNAME flattening.

### Verification
- `https://beyondtomorrow.world` → HTTP 200 ✅
- `https://beyondtomorrow.world/ghost/` → HTTP 200 ✅
- SSL auto-provisioned by Railway ✅

---

## Quick Reference

### Internal Service Networking

| Service | Internal Domain | Port |
|---------|----------------|------|
| Ghost | `ghost.railway.internal` | 2368 |
| MySQL | `mysql.railway.internal` | 3306 |
| pgvector | `pgvector.railway.internal` | 5432 |

### External Access (for local development/debugging)

| Service | Public Proxy | Port |
|---------|-------------|------|
| MySQL | `metro.proxy.rlwy.net` | 32958 |
| pgvector | `ballast.proxy.rlwy.net` | 32490 |

### Railway Project Values (caring-alignment)
- **Project ID:** 752fdaea-fd96-4521-bec6-b7d5ef451270
- **Environment:** production
- **Environment ID:** c9dfebe4-097a-4151-be37-2b1fcd414e74

### Volumes

| Service | Volume Name | Mount Path |
|---------|------------|------------|
| Ghost | `ghost-volume` | `/var/lib/ghost/content` |
| MySQL | `mysql-volume-5Iak` | `/var/lib/mysql` |
| pgvector | `pgvector-volume` | `/var/lib/postgresql` |

---

## Troubleshooting

### Domain Not Working
- Wait up to 48 hours for DNS propagation
- Verify no typos in DNS records
- Check Railway dashboard for verification status
- Clear browser cache and try incognito mode

### SSL Certificate Not Active
- Railway auto-provisions SSL after DNS verification
- Can take up to 24 hours after DNS propagates
- Check Railway logs for any errors

### "This site can't be reached"
- DNS records may not have propagated yet
- Verify CNAME target is exactly as Railway provided
- Check if old A records are conflicting

---

## Timeline Estimate

| Task | Time |
|------|------|
| Create website | 1-2 hours |
| Deploy to Railway | 15-30 minutes |
| Configure DNS | 10-15 minutes |
| DNS propagation | 5 min - 48 hours |
| **Total** | **~2-4 hours** (plus propagation wait) |

---

## Next Steps
- [ ] Delete the old `beyondtomorrow` static service from Railway dashboard (Settings → Delete Service)
- [ ] Update DNS CNAME records at registrar to point to new Railway targets
- [ ] Set up Ghost admin account at `https://beyondtomorrow.world/ghost/`
- [ ] Generate Ghost Admin API key (for publisher agent)
- [ ] Create GitHub Actions workflow for agent automation
- [ ] Configure Hostinger email IMAP for Railway worker
- [ ] Set up Railway Object Storage for knowledge corpus
- [ ] Build agent services (Orchestrator, Research, Writer, Editor, Publisher, Indexer)
- [ ] Set up Slack webhook alerts
- [ ] Upload initial PDFs to knowledge corpus
