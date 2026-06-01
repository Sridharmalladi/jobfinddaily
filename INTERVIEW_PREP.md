# jobfinddaily — Interview Preparation Guide

Everything you need to talk confidently about this project in any technical interview,
portfolio review, or casual conversation. Written from your perspective as the builder.

---

## What Is This Project?

jobfinddaily is a local MCP (Model Context Protocol) server I built in Python that runs
alongside Claude Desktop. Its job is to discover, filter, score, and surface high-quality
remote AI/ML engineering roles at startups — specifically ones that are relevant to
someone on STEM OPT looking for junior-friendly, US-based positions.

The core architectural principle I designed around is strict division of labor:
- The MCP handles all deterministic work: web scraping, API calls, filtering, deduplication,
  scoring, caching, and contact discovery.
- Claude (the LLM) only handles reasoning, summarization, and final presentation.
- The LLM never browses the internet or fetches data directly. Everything it receives
  has already been processed by the MCP.

This separation was intentional. LLMs are expensive, slow, and non-deterministic.
Filtering a job by whether it mentions "visa sponsorship" is a regex problem, not an
AI problem. I kept Claude focused on what it's actually good at.

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
     ├── tools/filtering.py    ← deterministic job filtering
     ├── tools/scoring.py      ← rule-based scoring system
     ├── tools/contacts.py     ← hiring contact discovery via Tavily
     └── tools/storage.py      ← SQLite: caching + job persistence
```

The server runs as a child process of Claude Desktop. Claude calls tools over stdio
using the MCP protocol. Each tool call is synchronous from Claude's perspective —
it blocks until the MCP returns a result.

---

## Data Sources

I chose free APIs with no credit card required for the MVP:

### HN Algolia API (free, no key)
Hacker News runs a "Who is Hiring?" thread every month. I use the Algolia search API
to find the latest thread, then search its comments for AI/ML keywords. This is one
of the highest-signal sources for startup jobs because technical founders post directly.

Algorithm: find the most recent thread by sorting hits by `created_at_i` (Unix timestamp),
then search comments within that thread using keyword OR queries. Parse each comment
as a free-form job posting.

### RemoteOK API (free, no key)
Returns a JSON array of remote tech jobs. First item is metadata, rest are job objects
with position, company, tags, description, and epoch timestamp. I filter client-side
using a compiled regex of keywords.

### Tavily Search API (1,000 free credits/month)
An AI-agent-optimized search API that accepts POST requests with JSON. I use it to
search ATS platforms (Ashby, Lever, Greenhouse) for AI/ML startup job postings.
I run 5 targeted queries concurrently and parse the results. Chosen over Google Custom
Search (100/day limit, verbose setup) and Exa (more expensive free tier).

### Firecrawl API (optional, for job page scraping)
Used in `extract_company_requirements` to scrape a job URL and return clean markdown.
Falls back to a custom httpx + BeautifulSoup4 scraper if no Firecrawl key is configured.

---

## Filtering System

**File:** `tools/filtering.py`

The filter runs before any scoring. It rejects jobs deterministically using regex
pattern matching — zero LLM calls, zero API calls.

### Why regex and not ML?
Regex is O(n) per pattern, fully explainable, instantly debuggable, and never
hallucinates. For a pass/fail gate where the rules are known upfront, it's the
right tool. I can add a rule in 30 seconds and know exactly what it does.

### Filter pipeline (in order):

**1. REJECT_TITLE** — Blocks senior/staff/lead/director titles
These roles typically require 5+ years of experience or management background.
Regex uses word boundaries to avoid false matches (e.g., "leadership" doesn't match "lead").

**2. NON_TECH_ROLE** — Blocks obvious non-engineering titles
Sales, ops, legal, finance, marketing roles that appear at AI companies but are
irrelevant. Added after the initial version let "Revenue Cycle Specialist at an AI
startup" pass through because the company description mentioned AI.

**3. TECH_TITLE** — Requires a technical keyword in the title
Title must contain: engineer, scientist, researcher, developer, intern, ML, AI, LLM,
data, NLP, etc. This catches roles like "Product Manager at an AI company" — the
company is AI, but the role is not.

**4. Strong tech signal count** — The most important gate
I maintain a list of ~70 specific technical keywords and require at least 2 to appear
in the combined title + description. These are terms that only appear in real AI/ML
engineering job descriptions:

- Model training: fine-tuning, LoRA, QLoRA, RLHF, PEFT, pretraining
- RAG & retrieval: RAG, vector database, embedding model, semantic search
- Vector DBs: Pinecone, ChromaDB, Weaviate, Qdrant, FAISS, Milvus
- LLM frameworks: LangChain, LlamaIndex, LangGraph, HuggingFace, DSPy, Haystack
- Agentic (2024-2025 wave): CrewAI, AutoGen, Pydantic AI, Smolagents, Instructor
- Local inference: llama.cpp, GGUF, vLLM, Ollama, MLX
- Training infra: CUDA, DeepSpeed, FSDP, distributed training, A100, H100
- MLOps: MLflow, W&B, Weights & Biases, model registry, feature store

Why the count approach instead of matching any one signal? Because "PyTorch" alone
appears in thousands of data science job descriptions including pure analyst roles.
Two specific signals together (e.g., "LangChain" + "vector database") are a much
stronger indicator that the job is actually about building LLM-powered systems.

**5. ENTERPRISE_SIGNAL** — Rejects Deloitte, Accenture, McKinsey, etc.
These firms hire AI talent but into consulting structures with slow pace, enterprise
clients, and little ownership. Not the startup environment I'm optimizing for.

**6. Experience years check**
Parses experience requirements like "3+ years", "5-7 years" using regex with
numeric capture groups. Rejects if max requirement >= 3 years. This catches roles
that use neutral-sounding titles but want experienced hires.

---

## Scoring System

**File:** `tools/scoring.py`

Every job that passes filtering gets a numeric score. This is a rule-based additive
scoring system — not ML, not embeddings, just weighted if-statements. The result
is an integer that determines ranking order.

### Why rule-based scoring and not a ranking model?

Three reasons:
1. I don't have labeled training data for "good job for me."
2. My preferences are explicit and known — I can write them down as rules.
3. Explainability matters. I can show exactly why a job scored 87 vs 42.

### Scoring table:

| Signal | Points | Logic |
|---|---|---|
| Strong LLM/RAG/agent signal | +20 | STRONG_AI regex on full text |
| AI Engineer title (application layer) | +12 | Titles: AI Engineer, LLM Engineer, Full-Stack AI |
| Startup / small-team | +20 | Keywords: startup, seed, YC, founding engineer, scrappy |
| Remote | +15 | Keywords: remote, WFH, distributed |
| Junior / entry-level / internship | +15 | Keywords: new grad, entry-level, 0-2 years, intern |
| AI-focused company | +10 | AI signal in company name or description |
| Builder culture | +10 | Keywords: ship, deploy, ownership, product-minded |
| Contract / short-term role | +12 | Keywords: contract, freelance, 1099, C2C, N-month contract |
| Visa / OPT sponsorship offered | +15 | Keywords: visa sponsor, H1B sponsor, OPT eligible |
| Fresh listing (≤7 days) | +8 | `age_days` field from source |
| US-based or US remote | +10 | Keywords: United States, US remote, Americas |
| **Penalties** | | |
| No visa sponsorship | -30 | Keywords: no sponsorship, US citizen only, cannot sponsor |
| Non-US only role | -20 | Keywords: UK only, EU only, APAC only |
| Stale listing (>60 days) | -20 | `age_days` field |
| Very stale listing (>90 days) | -40 | `age_days` field |
| Senior/staff/lead title | -25 | Redundant with filter but kept for re-scoring |
| Enterprise/consulting firm | -20 | Redundant with filter but kept for re-scoring |
| Pure backend without AI | -15 | backend/devops title + no AI signal |
| Pure analyst without ML | -15 | analyst title + no AI signal |

### Maximum possible score: ~147 (fresh AI Engineer role at a YC startup with visa sponsorship)

The visa penalty (-30) is intentionally the harshest single penalty. A job that
explicitly says "no sponsorship" is a hard dead end for someone on STEM OPT, so
it should be buried at the bottom of the list even if everything else looks great.

### Freshness signal

Age is sourced differently per platform:
- HN Hiring: `created_at_i` Unix timestamp from Algolia API
- RemoteOK: `epoch` Unix timestamp from the job object
- Tavily: no publish date available, stored as -1 (unknown, no penalty)

Age in days is calculated as `(current_time - posted_time) / 86400`.

---

## Caching System

**File:** `tools/storage.py`

SQLite database at `db/jobs.db` with two tables:

**`cache` table**: Key-value store where key is an MD5 hash of the query/URL
and value is JSON-serialized data. TTL is enforced at read time by comparing
`expires_at` to the current timestamp. If expired, treated as a cache miss.

- Job search results: 24-hour TTL (API calls are expensive, results don't change hourly)
- Contact lookups: 7-day TTL (LinkedIn profiles are stable)

**`jobs` table**: Persistent storage for jobs the user saves. Used for deduplication
across sessions — before scoring, we pull all saved URLs and (company, title) pairs
and exclude them from results. This prevents the same job appearing every day.

Why SQLite over Redis or a file-based cache? No dependencies, no server to run,
zero configuration. The database is a single file that lives in the project directory.
For a single-user local tool, SQLite's concurrent write limitations don't matter.

---

## Deduplication

`_dedupe()` in `tools/jobs.py` maintains two in-memory sets per run:
1. `seen_urls` — exact URL match
2. `seen_ct` — normalized (company.lower(), title.lower()) pair

A job is excluded if either its URL or its company+title pair has been seen before,
either in the current batch or in the saved jobs database. This prevents the same
opening appearing twice (once from HN, once from Tavily) and prevents jobs you've
already saved from showing up again tomorrow.

---

## Contact Discovery

**File:** `tools/contacts.py`

`find_hiring_people(company)` uses Tavily to search LinkedIn for founders, CTOs,
engineering leads, and recruiters at a given company. It runs 3 queries in sequence
and stops when it has 5 contacts.

Signal validation: a contact is only returned if a role keyword (founder, CEO, CTO,
VP Engineering, recruiter, etc.) is found in the title or snippet via regex. It never
guesses. If no role signal is found, the result is skipped entirely.

Name extraction: strips LinkedIn's title suffix pattern ("Name - Title | LinkedIn")
using two regex passes, leaving only the person's name.

---

## Key Architectural Decisions and Why I Made Them

### "Why not just let Claude search the web?"
Claude's web browsing is non-deterministic, can't be tuned for my specific filtering
rules, burns context window, and produces results I can't cache or deduplicate. By
doing all the data work in the MCP, I get reproducible results, 24-hour caching,
and zero LLM cost on the filtering layer.

### "Why not use a vector database for job matching?"
My matching criteria are explicit rules, not semantic similarity. "Does this job mention
RLHF?" is a substring check, not a cosine similarity problem. Adding a vector DB would
increase complexity without improving accuracy for this use case.

### "Why rule-based scoring instead of a learned ranking model?"
No training data, full explainability, instant iteration. When I see a bad result
I can trace exactly which rule let it through and fix it in 30 seconds. A learned
model would require labeled examples, a training pipeline, and a retraining loop.

### "Why did you change the AI signal check?"
Initially I checked for generic terms like "AI" and "ML" in the description. This let
through non-technical roles at AI companies — "Revenue Cycle Specialist at an AI startup"
passed because the company described themselves as AI-powered. I switched to counting
specific technical signals (framework names, model training terms, retrieval concepts)
and requiring at least 2 to match. "AI" in a description is now meaningless to me;
"LangGraph" + "fine-tuning" is a strong signal.

### "How do you handle jobs from different sources?"
Each source fetcher returns a normalized job dict with the same fields: company, title,
location, url, summary, source, description, age_days. This normalization layer means
filtering and scoring code is source-agnostic — it doesn't know or care whether a job
came from HN, RemoteOK, or Tavily.

### "What's the MCP protocol exactly?"
MCP (Model Context Protocol) is Anthropic's open standard for connecting LLMs to
external tools and data. The server exposes tools as JSON-schema-defined functions.
Claude Desktop launches the server as a child process and communicates over stdio.
When Claude needs job data, it calls a tool like `discover_jobs()` and the MCP server
handles all the actual work and returns structured data.

---

## Libraries and What They Actually Do

### `mcp[cli]` — FastMCP
Anthropic's Python SDK for building MCP servers. `FastMCP` is a decorator-based
framework similar to FastAPI. `@mcp.tool()` registers a function as a callable tool,
automatically generating the JSON schema from type hints.

### `httpx`
Async HTTP client. Used instead of `requests` because the job fetcher runs multiple
API calls concurrently using `asyncio.gather()`. `requests` is synchronous and would
serialize those calls; `httpx` allows them to run in parallel, cutting fetch time
roughly in proportion to the number of sources.

### `beautifulsoup4`
HTML parser for the fallback job page scraper. When Firecrawl isn't configured, I fetch
the raw HTML and use BeautifulSoup to extract text from `<p>`, `<li>`, `<h1-h3>`, `<div>`
tags while stripping scripts, styles, and nav elements. The underlying parser is Python's
built-in `html.parser`.

### `python-dotenv`
Loads environment variables from `.env` into `os.environ` at startup. This keeps API
keys out of the codebase.

### `pydantic`
Indirect dependency of `mcp`. Used internally for validating tool input/output schemas.

### `re` (stdlib)
Python's regex engine. All filtering and scoring uses pre-compiled `re.Pattern` objects
(via `re.compile()`) created at module load time. Pre-compiling avoids recompiling the
same pattern on every function call, which matters when filtering hundreds of jobs.

### `sqlite3` (stdlib)
Python's built-in SQLite interface. No ORM — raw SQL with parameterized queries to
prevent injection. Uses `INSERT OR IGNORE` for deduplication via UNIQUE constraints.

### `asyncio` (stdlib)
Python's async runtime. `asyncio.gather(*tasks)` runs the HN, RemoteOK, and Tavily
fetchers concurrently rather than sequentially. If each takes ~2 seconds, gather
brings total time to ~2 seconds instead of ~6 seconds.

### `hashlib` (stdlib)
MD5 hashing for cache keys. `hashlib.md5("|".join(parts).encode()).hexdigest()` produces
a stable 32-character key from any combination of query strings or URLs.

---

## What I Would Build Next

If I were extending this project:
- **Apollo.io integration**: Enrich company data with funding stage and headcount
  to better identify true early-stage startups vs. growth-stage companies calling
  themselves startups.
- **Application tracker**: Extend the SQLite schema to track application status,
  follow-up dates, and contact outreach.
- **Freshness via RSS**: Several ATS platforms expose RSS feeds. Subscribing would
  give real-time job posts instead of polling.
- **Resume gap analysis**: After extracting requirements from a job page, compare
  the required skills against a stored resume to surface gaps.
- **Email draft generation**: After `find_hiring_people` returns a contact, generate
  a cold outreach email tailored to the role and their background.
