# jobfinddaily

Finds remote AI/ML jobs at startups, filters out the ones you can't get, and tracks the ones you apply to.

Runs as a local MCP server. Your assistant calls it, you talk to your assistant in plain English.

Built for junior engineers and STEM OPT candidates, so it aggressively drops senior roles, enterprise consulting, and anything that says no visa sponsorship.

---

## What a day looks like

```
You:  find me jobs
      → 30 roles, scored, best first, already filtered

You:  tell me about the top one
      → required skills, their AI stack, what they actually want

You:  who do I talk to there
      → founders, CTOs, recruiters, with LinkedIn links

You:  I applied to it
      → tracked

You:  what's my pipeline
      → 12 open, 3 gone quiet, here's who to chase
```

---

## Setup

You need Python 3.11+ and a free [Tavily](https://tavily.com) key (1,000 searches/month, no card).

```bash
git clone https://github.com/Sridharmalladi/jobfinddaily.git
cd jobfinddaily
pip install -r requirements.txt
cp .env.example .env        # put your Tavily key in it
```

Point your MCP client at it. For Claude Desktop that's `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "jobfinddaily": {
      "command": "python",
      "args": ["/full/path/to/jobfinddaily/mcp_server.py"]
    }
  }
}
```

Restart the app. Tools show up on their own.

---

## The tools

**Finding work**

| | |
|---|---|
| `discover_jobs` | Pulls from HN "Who is Hiring", RemoteOK, and startup ATS boards. Filters and scores before returning. Top 30, cached 24h. |
| `extract_company_requirements` | Reads a job page and pulls out skills, AI stack, experience level, culture. |
| `find_hiring_people` | Founders, CTOs, recruiters at a company, with LinkedIn links. Only returns people with a confirmed role — never guesses. |
| `job_report` | Top N jobs with requirements and contacts already attached. |

**Tracking what you did about it**

| | |
|---|---|
| `track_application` | Move a job through `interested → applied → screening → interviewing → offer`, or `rejected` / `ghosted`. Keyed on the job URL, so it updates instead of duplicating. |
| `application_pipeline` | Everything open, your response rate, and which applications have gone quiet past their stage's threshold — each with a suggested next move. |
| `untrack_application` | Drop one. |

**Housekeeping**

`save_jobs` · `get_saved_jobs` · `score_jobs` — persist to local SQLite, re-rank a custom list.

---

## How jobs get picked

No LLM in the pipeline. All regex, all deterministic, so it costs nothing and behaves the same every run.

**Thrown out:** senior/staff/lead/director titles · sales, ops, legal, finance, marketing · Deloitte, Accenture, McKinsey, Big 4 · anything asking 3+ years · anything with no real AI/ML signal in the text.

**Scored up:** LLM/RAG/agent work `+20` · startup signals `+20` · remote `+15` · junior-friendly `+15` · visa sponsorship `+15` · fresh listing `+8`

**Scored down:** no sponsorship `-30` · stale 90+ days `-40` · senior title `-25` · non-US only `-20`

Highest score first. Everything is additive and lives in `tools/scoring.py` if you want different weights.

---

## Follow-up rules

`application_pipeline` flags anything sitting too long:

| Stage | Nudges after |
|---|---|
| interested | 3 days |
| applied | 7 days |
| screening | 5 days |
| interviewing | 5 days |

Closed stages are never chased. Change the numbers in `tools/pipeline.py`.

---

## Where things live

```
mcp_server.py       the 10 tools
tools/jobs.py       fetching and scraping
tools/filtering.py  what gets thrown out
tools/scoring.py    what gets ranked up
tools/contacts.py   finding hiring people
tools/pipeline.py   application tracking
tools/storage.py    SQLite, caching, persistence
```

Your database sits at `db/jobs.db` and is gitignored. Job searches cache for 24h, contact lookups for 7 days.

---

## Notes

- Firecrawl is optional. Without a key it scrapes with httpx + BeautifulSoup, which is fine for most job pages.
- `mcp` is pinned below 2.0 — v2 renamed `FastMCP` and this runs on the v1 API.
- Nothing leaves your machine except the API calls to Tavily and the job boards.
