import os
from pathlib import Path

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from tools.storage import init_db

load_dotenv(dotenv_path=Path(__file__).parent / ".env")

TAVILY_KEY = os.getenv("TAVILY_API_KEY", "")
FIRECRAWL_KEY = os.getenv("FIRECRAWL_API_KEY", "")

init_db()

mcp = FastMCP(
    "jobfinddaily",
    instructions=(
        "Job discovery MCP for remote AI/ML startup roles. "
        "Call discover_jobs to find new opportunities (pre-filtered, pre-scored). "
        "Use extract_company_requirements(url) to understand what a company wants. "
        "Use find_hiring_people(company) to locate founders/CTOs/recruiters. "
        "Use score_jobs to re-rank a custom list. "
        "Call save_jobs to persist results and get_saved_jobs to review history. "
        "Web search powered by Tavily. Requires TAVILY_API_KEY in .env."
    ),
)


@mcp.tool()
async def discover_jobs() -> list[dict]:
    """
    Search HN Hiring, RemoteOK, and Tavily for remote AI/ML startup jobs.
    Results are pre-filtered (no senior/enterprise/pure-backend roles) and
    pre-scored by startup fit + AI relevance. Returns up to 30 jobs sorted
    by score. Caches results for 24 hours.
    """
    from tools.jobs import discover_jobs as _run
    return await _run(TAVILY_KEY, FIRECRAWL_KEY)


@mcp.tool()
async def extract_company_requirements(url: str) -> dict:
    """
    Scrape a job posting URL and extract structured hiring requirements.
    Returns: required_skills, ai_stack, experience_level,
             company_expectations (bullet points), culture_signals.
    Uses Firecrawl when configured, otherwise falls back to direct scraping.
    Results cached for 24 hours.
    """
    from tools.jobs import extract_requirements
    return await extract_requirements(url, FIRECRAWL_KEY)


@mcp.tool()
async def find_hiring_people(company: str) -> dict:
    """
    Find founders, CTOs, engineering leads, and recruiters at a company
    via Tavily Search of public LinkedIn pages.
    Returns contacts with name, role, and linkedin URL.
    Only returns contacts with a verified role signal — never guesses.
    Results cached for 7 days. Requires TAVILY_API_KEY.
    """
    from tools.contacts import find_hiring_people as _run
    return await _run(company, TAVILY_KEY)


@mcp.tool()
async def job_report(limit: int = 5) -> list[dict]:
    """
    Full enriched report for the top N jobs (default 5).
    For each job returns:
      - title, company, score, experience_level, apply_url, age_days
      - required_skills, ai_stack, what_they_want (bullet points), culture_signals
      - hiring_contacts: list of {name, role, linkedin}
    Runs discover_jobs, then enriches each result with requirements and contacts.
    Present to user as: score + title, apply link, founder/contact links, what they want.
    """
    import asyncio
    from tools.jobs import discover_jobs as _discover, extract_requirements
    from tools.contacts import find_hiring_people as _contacts

    jobs = await _discover(TAVILY_KEY, FIRECRAWL_KEY)
    top = jobs[:limit]

    async def _enrich(job: dict) -> dict:
        url = job.get("url", "")
        company = job.get("company", "")
        reqs, contacts = await asyncio.gather(
            extract_requirements(url, FIRECRAWL_KEY),
            _contacts(company, TAVILY_KEY),
            return_exceptions=True,
        )
        reqs = reqs if isinstance(reqs, dict) else {}
        contacts = contacts if isinstance(contacts, dict) else {}
        return {
            "title": job.get("title", ""),
            "company": company,
            "score": job.get("score", 0),
            "apply_url": url,
            "location": job.get("location", ""),
            "age_days": job.get("age_days", -1),
            "source": job.get("source", ""),
            "experience_level": reqs.get("experience_level", "not specified"),
            "required_skills": reqs.get("required_skills", []),
            "ai_stack": reqs.get("ai_stack", []),
            "what_they_want": reqs.get("company_expectations", []),
            "culture_signals": reqs.get("culture_signals", []),
            "hiring_contacts": contacts.get("contacts", []),
        }

    return await asyncio.gather(*[_enrich(j) for j in top])


@mcp.tool()
def score_jobs(jobs: list[dict]) -> list[dict]:
    """
    Score and rank a list of job dicts by startup fit and AI relevance.
    Scoring: +20 LLM/RAG/agents, +20 startup signals, +15 remote,
             +15 junior-friendly, +10 AI company, +10 builder culture.
    Penalties: -25 senior/lead, -20 enterprise, -15 pure backend/analyst.
    Returns list of {job, score, reasons} sorted descending.
    """
    from tools.scoring import score_jobs as _run
    return _run(jobs)


@mcp.tool()
def save_jobs(jobs: list[dict]) -> dict:
    """
    Persist jobs to local SQLite for deduplication and session continuity.
    Each job dict should have: company, title, url, score, source, location, summary.
    Silently skips exact duplicates (same company+title or same URL).
    Returns {saved, skipped}.
    """
    from tools.storage import save_job
    saved = 0
    for j in jobs:
        if save_job(
            company=j.get("company", ""),
            title=j.get("title", ""),
            url=j.get("url", ""),
            score=j.get("score", 0),
            source=j.get("source", ""),
            location=j.get("location", ""),
            summary=j.get("summary", ""),
        ):
            saved += 1
    return {"saved": saved, "skipped": len(jobs) - saved}


@mcp.tool()
def get_saved_jobs(limit: int = 50) -> list[dict]:
    """
    Retrieve previously saved jobs from the local SQLite database.
    Sorted by score descending. Use for deduplication awareness and
    to review past discoveries without re-fetching APIs.
    """
    from tools.storage import get_saved_jobs as _run
    return _run(limit)


if __name__ == "__main__":
    mcp.run()
