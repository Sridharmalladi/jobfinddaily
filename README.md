# jobfinddaily

A local MCP (Model Context Protocol) server that runs alongside Claude Desktop to discover, filter, score, and surface high-quality remote AI/ML engineering jobs at startups — optimized for junior engineers and STEM OPT candidates.

Built with Python, FastMCP, SQLite, and async HTTP. Zero LLM calls in the data pipeline — all filtering and scoring is deterministic regex.

---

## Architecture

```
Claude Desktop
     │
     │  MCP protocol (stdio)
     ▼
mcp_server.py          ← FastMCP server, exposes 6 tools
     │
     ├── tools/jobs.py         ← source fetching, scraping, aggregation
     ├── tools/filtering.py    ← deterministic job filtering (regex only)
     ├── tools/scoring.py      ← rule-based additive scoring system
     ├── tools/contacts.py     ← hiring contact discovery via Tavily
     └── tools/storage.py      ← SQLite: 24h/7d caching + job persistence
```

The MCP server runs as a child process of Claude Desktop. Claude calls tools over stdio using the MCP protocol. All data work happens in the server — the LLM only handles reasoning and presentation.

---

## Tools Exposed to Claude

| Tool | Description |
|---|---|
| `discover_jobs` | Fetches from HN Hiring, RemoteOK, and Tavily. Pre-filters and pre-scores. Returns up to 30 jobs sorted by score. Results cached 24h. |
| `extract_company_requirements` | Scrapes a job URL and extracts required skills, AI stack, experience level, culture signals. |
| `find_hiring_people` | Searches LinkedIn (via Tavily) for founders, CTOs, and recruiters at a company. Returns verified contacts with name, role, and LinkedIn URL. |
| `job_report` | Full enriched report for top N jobs: requirements + hiring contacts combined. |
| `score_jobs` | Scores and ranks a custom list of job dicts. |
| `save_jobs` / `get_saved_jobs` | Persist and retrieve jobs from local SQLite for deduplication across sessions. |

---

## Data Sources

- **HN Algolia API** (free, no key) — searches the monthly "Who is Hiring?" thread for AI/ML comments
- **RemoteOK API** (free, no key) — remote tech jobs filtered client-side by keyword regex
- **Tavily Search API** (1,000 free credits/month) — ATS platform searches (Ashby, Lever, Greenhouse)
- **Firecrawl API** (optional) — clean markdown extraction from job pages; falls back to httpx + BeautifulSoup4

---

## Filtering System

All filtering in `tools/filtering.py` is deterministic regex — no LLM, no API calls.

Pipeline (in order):
1. **REJECT_TITLE** — blocks senior/staff/lead/director titles
2. **NON_TECH_ROLE** — blocks sales, ops, legal, finance, marketing
3. **TECH_TITLE** — requires engineer/scientist/researcher/intern/ML/AI/LLM in the title
4. **Strong tech signal count** — requires ≥1 match from a list of ~70 specific terms (fine-tuning, LoRA, RAG, LangChain, vLLM, CUDA, etc.)
5. **ENTERPRISE_SIGNAL** — rejects Deloitte, Accenture, McKinsey, Big 4
6. **Experience years** — rejects if max stated requirement ≥ 3 years

---

## Scoring System

Additive rule-based scoring in `tools/scoring.py`. Every job that passes filtering gets a numeric score.

| Signal | Points |
|---|---|
| Strong LLM/RAG/agent signal | +20 |
| AI Engineer title (application layer) | +12 |
| Startup / small-team signal | +20 |
| Remote | +15 |
| Junior / entry-level / internship | +15 |
| Visa / OPT sponsorship offered | +15 |
| Contract / short-term role | +12 |
| AI-focused company | +10 |
| Builder culture | +10 |
| US-based or US remote | +10 |
| Fresh listing (≤7 days) | +8 |
| **No visa sponsorship** | **-30** |
| Non-US only | -20 |
| Stale listing (>60d) | -20 |
| Very stale listing (>90d) | -40 |
| Senior/staff/lead title | -25 |
| Enterprise/consulting | -20 |

---

## Caching

SQLite database at `db/jobs.db` with a key-value cache table:
- Job search results: **24-hour TTL**
- Contact lookups: **7-day TTL**

Cache keys are MD5 hashes of the query/URL. Expiry enforced at read time.

---

## Setup

**Requirements:** Python 3.11+

```bash
git clone https://github.com/Sridharmalladi/jobfinddaily.git
cd jobfinddaily
pip install -r requirements.txt
cp .env.example .env
# add your Tavily API key to .env
```

**Configure Claude Desktop** — add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "jobfinddaily": {
      "command": "python",
      "args": ["/path/to/jobfinddaily/mcp_server.py"]
    }
  }
}
```

Then restart Claude Desktop. The tools will appear automatically.

**Get a Tavily API key:** [tavily.com](https://tavily.com) — 1,000 free credits/month, no credit card required.

---

## Stack

- Python 3.11
- [FastMCP](https://github.com/jlowin/fastmcp) — MCP server framework
- httpx — async HTTP
- BeautifulSoup4 — HTML scraping fallback
- sqlite3 (stdlib) — caching and job persistence
- python-dotenv — environment variable loading
