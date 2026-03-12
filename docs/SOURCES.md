# Research Sources & APIs

Approved domains and API configurations for the BeyondTomorrow.World research agent.

> **This file is the human-readable companion to [`config/sources.yaml`](../config/sources.yaml).**  
> Edit `config/sources.yaml` to change what the agent is allowed to fetch.  
> Edit this file to document the reasoning behind each source.

---

## Search Engines

| Engine | Package / API | Auth Required | Default Results | Notes |
|--------|--------------|---------------|-----------------|-------|
| **DuckDuckGo** | `duckduckgo_search` | None | 10 | Primary web search. No sign-up, no rate limit for normal use. |
| **arXiv** | `arxiv` Python pkg | None | 5 | Academic preprints. Filter by subject category in `sources.yaml`. |
| **PubMed** | NCBI Entrez API | Optional (`NCBI_API_KEY`) | 5 | Biomedical literature. Free tier: 3 req/s; with key: 10 req/s. |
| **Semantic Scholar** | S2 Graph API | Optional (`SEMANTIC_SCHOLAR_API_KEY`) | 5 | AI-assisted academic search. Unauthenticated: 100 req/5 min. |

---

## Approved Domains by Category

### Academic / Peer-Reviewed

| Domain | Credibility (1–5) | API Available | Notes |
|--------|------------------|---------------|-------|
| arxiv.org | ★★★★☆ | arXiv API (via `arxiv` pkg) | Open-access preprints. Always cross-check for published version. |
| nature.com | ★★★★★ | None (scrape) | Nature Portfolio journals. High-impact peer review. |
| science.org | ★★★★★ | None (scrape) | Science / AAAS. Flagship multidisciplinary journal. |
| pnas.org | ★★★★★ | None (scrape) | PNAS — broad scientific coverage, open access after 6 months. |
| cell.com | ★★★★★ | None (scrape) | Cell Press — life sciences, medicine, sustainability. |
| thelancet.com | ★★★★★ | None (scrape) | Global health and climate-health nexus. |
| pubmed.ncbi.nlm.nih.gov | ★★★★★ | NCBI Entrez (free) | Citation index. Retrieve full text via DOI or publisher. |
| semanticscholar.org | ★★★★☆ | S2 Graph API (free) | Good for finding related papers. |
| jstor.org | ★★★★★ | None (scrape) | Archive. Many articles now open access. |
| ssrn.com | ★★★☆☆ | None (scrape) | Social science preprints — not peer-reviewed. |

### Climate / Environment

| Domain | Credibility | API Available | Notes |
|--------|------------|---------------|-------|
| ipcc.ch | ★★★★★ | None (scrape) | UN IPCC reports — definitive scientific consensus. |
| climate.nasa.gov | ★★★★★ | NASA APIs (free) | Satellite data, global temperature anomaly datasets. |
| noaa.gov | ★★★★★ | NOAA CDO API (free, key needed) | Authoritative weather and climate data. Env var: `NOAA_API_KEY` |
| climate.gov | ★★★★★ | None (scrape) | NOAA's public climate explainer portal. |
| carbonbrief.org | ★★★★☆ | None (scrape) | Specialist climate journalism. Rigorous sourcing. |
| climatecentral.org | ★★★★☆ | None (scrape) | Excellent data visualisations on climate impacts. |
| globalforestwatch.org | ★★★★☆ | GFW API (free) | Near-real-time deforestation and fire monitoring. |
| iea.org | ★★★★★ | IEA Data API (free, key needed) | Authoritative global energy statistics. Env var: `IEA_API_KEY` |
| irena.org | ★★★★★ | None (scrape) | Renewable energy capacity and transition data. |

### Technology / AI

| Domain | Credibility | API Available | Notes |
|--------|------------|---------------|-------|
| technologyreview.com | ★★★★☆ | None (scrape) | MIT Tech Review — rigorous tech journalism. |
| spectrum.ieee.org | ★★★★☆ | None (scrape) | IEEE Spectrum — engineering-focused. |
| arstechnica.com | ★★★☆☆ | None (scrape) | Good technical depth; broad coverage. |
| wired.com | ★★★☆☆ | None (scrape) | Digital culture, technology, science. |
| quantamagazine.org | ★★★★☆ | None (scrape) | Excellent maths and science journalism. |
| theatlantic.com | ★★★☆☆ | None (scrape) | Long-form on technology, policy, climate. |
| deepmind.com | ★★★★☆ | None (scrape) | DeepMind research blog — primary source for their work. |
| openai.com | ★★★★☆ | None (scrape) | OpenAI research blog — primary source. |

### Policy / Geopolitics

| Domain | Credibility | API Available | Notes |
|--------|------------|---------------|-------|
| foreignaffairs.com | ★★★★☆ | None (scrape) | Leading international relations journal. |
| rand.org | ★★★★★ | None (scrape) | Nonpartisan; rigorous primary research. |
| carnegieendowment.org | ★★★★☆ | None (scrape) | Carnegie — foreign policy, nuclear security. |
| chathamhouse.org | ★★★★☆ | None (scrape) | Chatham House — international affairs, energy. |
| brookings.edu | ★★★★☆ | None (scrape) | Centre-left US policy research. |
| un.org | ★★★★★ | UN Data API (free) | Official UN reports and datasets. |
| worldbank.org | ★★★★★ | World Bank API (free) | Development data. Env var: none required. |
| imf.org | ★★★★★ | IMF Data API (free) | Global economic outlook, fiscal data. |

### News

| Domain | Credibility | API Available | Notes |
|--------|------------|---------------|-------|
| theguardian.com | ★★★☆☆ | Guardian API (free, key needed) | Strong environment desk. Env var: `GUARDIAN_API_KEY` |
| reuters.com | ★★★★☆ | Reuters API (paid) | Wire service — high-accuracy factual reporting. |
| apnews.com | ★★★★☆ | None (scrape) | AP wire service. Free scraping. |
| bbc.com | ★★★★☆ | BBC Feeds (RSS) | Strong science and climate online. |
| ft.com | ★★★★☆ | None (scrape) | Energy transition, economics, geopolitics. |
| economist.com | ★★★★☆ | None (scrape) | Data-driven analysis. |

### Open Data

| Domain | Credibility | API Available | Notes |
|--------|------------|---------------|-------|
| ourworldindata.org | ★★★★★ | OWID API (free) | Citable, well-sourced data visualisations. |
| data.worldbank.org | ★★★★★ | World Bank API (free) | Comprehensive development indicators. |
| stats.oecd.org | ★★★★★ | OECD API (free) | OECD member country statistics. |
| earthdata.nasa.gov | ★★★★★ | NASA Earthdata API (free, key needed) | Satellite climate datasets. Env var: `NASA_EARTHDATA_TOKEN` |

---

## Optional API Keys

Set these environment variables in Railway (or your `.env`) to unlock higher rate limits or paywalled content:

| Variable | Service | Required? |
|----------|---------|-----------|
| `NCBI_API_KEY` | PubMed / NCBI Entrez | Optional — 10 req/s vs 3 req/s |
| `SEMANTIC_SCHOLAR_API_KEY` | Semantic Scholar | Optional — higher rate limits |
| `NOAA_API_KEY` | NOAA Climate Data Online | Required for CDO API |
| `IEA_API_KEY` | IEA Data API | Required for detailed datasets |
| `GUARDIAN_API_KEY` | The Guardian Open Platform | Required for search API |
| `NASA_EARTHDATA_TOKEN` | NASA Earthdata | Required for direct dataset downloads |

API key registration links are in [AGENT_SETUP.md](AGENT_SETUP.md).

---

## Blocked Domains

The following are explicitly blocked regardless of what DuckDuckGo returns:

`facebook.com` · `twitter.com` · `x.com` · `instagram.com` · `tiktok.com` · `reddit.com` · `pinterest.com` · `quora.com` · `medium.com` · `substack.com`

> **Note:** `medium.com` and `substack.com` block individual posts (not the whole platform) by default. They can be unblocked per-task if a specific trusted author's post needs to be fetched.

---

## Adding a New Source

1. Add an entry to [`config/sources.yaml`](../config/sources.yaml) under `approved_domains`.
2. Set a realistic `credibility` score (1–5) based on editorial standards and peer-review status.
3. Add a row to the appropriate table in this file with notes on any API requirements.
4. If the source requires an API key, document it in the **Optional API Keys** table above and add the env var name to the entry in `sources.yaml`.
