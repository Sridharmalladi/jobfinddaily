import asyncio
import hashlib
import re
import time

import httpx
from bs4 import BeautifulSoup

from tools.filtering import filter_jobs
from tools.scoring import score_job
from tools.storage import (
    CACHE_TTL_JOBS,
    get_cache,
    get_saved_company_titles,
    get_saved_urls,
    set_cache,
)

TAVILY_URL = "https://api.tavily.com/search"
FIRECRAWL_URL = "https://api.firecrawl.dev/v1/scrape"
HN_ALGOLIA = "https://hn.algolia.com/api/v1/search"
REMOTEOK_API = "https://remoteok.com/api"

MAX_DESC = 280        # chars returned per job in summary
MAX_PER_SOURCE = 20
TOP_JOBS = 30

_ATS_COMPANY = re.compile(
    r"(?:jobs\.ashbyhq\.com|lever\.co|boards\.greenhouse\.io|"
    r"apply\.workable\.com|jobs\.lever\.co)/([^/?#]+)",
    re.IGNORECASE,
)
_JOB_TITLE_KW = re.compile(
    r"\b(engineer|scientist|researcher|developer|ml|ai|llm|nlp|intern|"
    r"analyst|architect|data|applied)\b",
    re.IGNORECASE,
)

# Skills extracted deterministically by extract_requirements
_ALL_SKILLS = [
    "Python", "JavaScript", "TypeScript", "Go", "Rust", "Java", "C++", "SQL",
    "PyTorch", "TensorFlow", "JAX", "scikit-learn", "Keras", "XGBoost",
    "LangChain", "LlamaIndex", "LangGraph", "OpenAI", "Anthropic",
    "HuggingFace", "Hugging Face", "ChromaDB", "Pinecone", "Weaviate",
    "FAISS", "Qdrant", "AWS", "GCP", "Azure", "Docker", "Kubernetes",
    "Spark", "dbt", "Airflow", "Databricks", "Ray", "MLflow",
    "FastAPI", "Flask", "Django", "React", "PostgreSQL", "Redis",
]
_AI_STACK = {
    "PyTorch", "TensorFlow", "JAX", "LangChain", "LlamaIndex", "LangGraph",
    "OpenAI", "Anthropic", "HuggingFace", "Hugging Face", "ChromaDB",
    "Pinecone", "Weaviate", "FAISS", "Qdrant", "scikit-learn", "MLflow", "Ray",
}
_CULTURE_TERMS = {
    "startup": ["startup", "early stage", "seed", "series a", "yc", "y combinator"],
    "remote": ["remote", "distributed", "wfh", "work from anywhere"],
    "fast-paced": ["fast-paced", "fast paced", "move fast", "scrappy", "high velocity"],
    "product-minded": ["product-minded", "product minded", "end-to-end", "full product"],
    "ownership": ["ownership", "autonomy", "high impact", "founding member", "founding engineer"],
    "junior-friendly": ["new grad", "entry level", "junior", "no experience required", "0-2 years"],
}


# ── helpers ──────────────────────────────────────────────────────────────────

def _key(*parts: str) -> str:
    return hashlib.md5("|".join(parts).encode()).hexdigest()


def _trunc(text: str, n: int = MAX_DESC) -> str:
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text).strip()
    return text[:n] + "…" if len(text) > n else text


def _company_from_url(url: str) -> str:
    m = _ATS_COMPANY.search(url)
    return m.group(1).replace("-", " ").title() if m else ""


def _parse_search_result(r: dict, source: str) -> dict:
    title = r.get("title", "")
    url = r.get("url", "")
    snippet = r.get("snippet", "") or r.get("description", "")

    company = _company_from_url(url)
    job_title = title

    if not company:
        for sep in (" at ", " | ", " - ", " – ", " — "):
            if sep in title:
                parts = title.split(sep, 1)
                if _JOB_TITLE_KW.search(parts[0]):
                    job_title, company = parts[0].strip(), parts[1].strip()
                elif _JOB_TITLE_KW.search(parts[1]):
                    job_title, company = parts[1].strip(), parts[0].strip()
                break

    full = f"{title} {snippet}"
    return {
        "company": company,
        "title": job_title,
        "location": "Remote" if re.search(r"\bremote\b", full, re.I) else "",
        "url": url,
        "summary": _trunc(snippet),
        "source": source,
        "description": snippet,
    }


def _dedupe(
    jobs: list[dict],
    saved_urls: set[str],
    saved_ct: set[tuple[str, str]],
) -> list[dict]:
    seen_urls = set(saved_urls)
    seen_ct = set(saved_ct)
    out = []
    for job in jobs:
        url = job.get("url", "")
        ct = (job.get("company", "").lower(), job.get("title", "").lower())
        if url and url in seen_urls:
            continue
        if ct[0] and ct in seen_ct:
            continue
        if url:
            seen_urls.add(url)
        if ct[0]:
            seen_ct.add(ct)
        out.append(job)
    return out


# ── source fetchers ───────────────────────────────────────────────────────────

async def _tavily(query: str, api_key: str, count: int = 10) -> list[dict]:
    if not api_key:
        return []
    ck = _key("tavily", query)
    if (c := get_cache(ck)) is not None:
        return c
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            TAVILY_URL,
            json={"api_key": api_key, "query": query, "max_results": count,
                  "search_depth": "basic", "include_answer": False},
        )
        resp.raise_for_status()
    results = [
        {"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("content", "")}
        for r in resp.json().get("results", [])
    ]
    set_cache(ck, results)
    return results


async def _tavily_jobs(api_key: str) -> list[dict]:
    queries = [
        'site:ashbyhq.com OR site:lever.co OR site:greenhouse.io AI engineer startup remote',
        'LLM engineer OR ML engineer startup remote junior hiring',
        'founding engineer AI startup remote',
        'YC startup AI engineer OR ML engineer hiring remote',
        'applied AI OR AI agent engineer startup remote junior',
    ]
    raw: list[dict] = []
    for q in queries:
        for r in await _tavily(q, api_key, count=8):
            raw.append(_parse_search_result(r, "Tavily Search"))
    return raw[:MAX_PER_SOURCE * 2]


async def _hn_hiring(keywords: list[str]) -> list[dict]:
    ck = _key("hn", *sorted(keywords))
    if (c := get_cache(ck)) is not None:
        return c

    async with httpx.AsyncClient(timeout=15) as client:
        # Latest "Who is Hiring?" thread
        tr = await client.get(
            HN_ALGOLIA,
            params={"query": "Ask HN: Who is hiring?", "tags": "story,ask_hn",
                    "numericFilters": "num_comments>50", "hitsPerPage": 5},
        )
        tr.raise_for_status()
        hits = tr.json().get("hits", [])
        if not hits:
            return []

        thread_id = sorted(hits, key=lambda h: h.get("created_at_i", 0), reverse=True)[0]["objectID"]

        # Search comments for AI/ML keywords
        cr = await client.get(
            HN_ALGOLIA,
            params={
                "query": " OR ".join(keywords[:4]),
                "tags": f"comment,story_{thread_id}",
                "hitsPerPage": 40,
            },
        )
        cr.raise_for_status()
        comments = cr.json().get("hits", [])

    jobs = []
    for c in comments:
        text = c.get("comment_text", "")
        if not text:
            continue
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if not lines:
            continue
        first = lines[0]
        co_parts = re.split(r"\s*[\|–—]\s*", first)
        company = co_parts[0].strip() if co_parts else ""

        title_match = next(
            (l for l in lines if re.search(r"\b(engineer|scientist|ml|ai|llm|intern)\b", l, re.I)),
            first,
        )
        location = ""
        if m := re.search(r"\b(remote|onsite|hybrid|san francisco|new york|london|berlin)\b", text, re.I):
            location = m.group(0).title()

        created_at = c.get("created_at_i", 0)
        age_days = int((time.time() - created_at) / 86400) if created_at else -1
        jobs.append({
            "company": company,
            "title": _trunc(title_match, 80),
            "location": location,
            "url": f"https://news.ycombinator.com/item?id={c.get('objectID', '')}",
            "summary": _trunc(" ".join(lines[:3])),
            "source": "HN Hiring",
            "description": _trunc(text, 500),
            "age_days": age_days,
        })

    result = jobs[:MAX_PER_SOURCE]
    set_cache(ck, result)
    return result


async def _remoteok(keywords: list[str]) -> list[dict]:
    ck = _key("remoteok", *sorted(keywords))
    if (c := get_cache(ck)) is not None:
        return c

    async with httpx.AsyncClient(timeout=20, headers={"User-Agent": "jobfinddaily/1.0"}) as client:
        resp = await client.get(REMOTEOK_API)
        resp.raise_for_status()
        data = resp.json()

    kw_re = re.compile("|".join(re.escape(k) for k in keywords), re.IGNORECASE)
    jobs = []
    for j in data[1:]:  # first item is metadata
        combined = f"{j.get('position', '')} {' '.join(j.get('tags', []))} {j.get('description', '')}"
        if not kw_re.search(combined):
            continue
        epoch = j.get("epoch", 0)
        age_days = int((time.time() - epoch) / 86400) if epoch else -1
        jobs.append({
            "company": j.get("company", ""),
            "title": j.get("position", ""),
            "location": "Remote",
            "url": j.get("url", ""),
            "summary": _trunc(j.get("description", "")),
            "source": "RemoteOK",
            "description": j.get("description", ""),
            "age_days": age_days,
        })
        if len(jobs) >= MAX_PER_SOURCE:
            break

    set_cache(ck, jobs)
    return jobs


# ── scraping helpers ──────────────────────────────────────────────────────────

async def _firecrawl(url: str, api_key: str) -> str:
    ck = _key("fc", url)
    if (c := get_cache(ck)) is not None:
        return c.get("md", "") if isinstance(c, dict) else ""

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            FIRECRAWL_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={"url": url, "formats": ["markdown"], "onlyMainContent": True},
        )
        resp.raise_for_status()
        md = resp.json().get("data", {}).get("markdown", "")

    set_cache(ck, {"md": md})
    return md


async def _scrape_simple(url: str) -> str:
    ck = _key("scrape", url)
    if (c := get_cache(ck)) is not None:
        return c.get("text", "") if isinstance(c, dict) else ""

    try:
        async with httpx.AsyncClient(
            timeout=15, headers={"User-Agent": "Mozilla/5.0 jobfinddaily/1.0"}
        ) as client:
            resp = await client.get(url, follow_redirects=True)
            resp.raise_for_status()
            html = resp.text
    except httpx.HTTPError:
        return ""

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
        tag.decompose()

    text = " ".join(
        el.get_text(" ", strip=True)
        for el in soup.find_all(["p", "li", "h1", "h2", "h3", "span", "div"])
        if el.get_text(strip=True)
    )
    text = re.sub(r"\s+", " ", text).strip()[:6000]
    set_cache(ck, {"text": text})
    return text


# ── requirement extraction (deterministic) ────────────────────────────────────

def _parse_requirements(content: str) -> dict:
    cl = content.lower()

    found_skills = [s for s in _ALL_SKILLS if s.lower() in cl]
    ai_stack = [s for s in found_skills if s in _AI_STACK]

    if any(t in cl for t in ["entry level", "entry-level", "new grad", "junior", "0-2", "1-2", "no experience"]):
        exp_level = "entry/junior"
    elif any(t in cl for t in ["senior", "5+ years", "7+ years", "8+ years", "10+ years"]):
        exp_level = "senior"
    elif any(t in cl for t in ["mid", "3-5 years", "2-4 years", "3+ years"]):
        exp_level = "mid-level"
    else:
        exp_level = "not specified"

    # Extract bulleted requirements (lines starting with -, *, •)
    bullets = [
        line.lstrip("-*•· ").strip()
        for line in content.split("\n")
        if re.match(r"^\s*[-*•·]", line) and len(line.strip()) > 10
    ][:6]

    culture = [
        signal
        for signal, terms in _CULTURE_TERMS.items()
        if any(t in cl for t in terms)
    ]

    return {
        "required_skills": found_skills[:12],
        "ai_stack": ai_stack,
        "experience_level": exp_level,
        "company_expectations": bullets,
        "culture_signals": culture,
    }


# ── public API ────────────────────────────────────────────────────────────────

async def discover_jobs(tavily_api_key: str = "", firecrawl_api_key: str = "") -> list[dict]:
    keywords = ["AI", "ML", "LLM", "machine learning", "RAG", "agents", "NLP"]

    tasks: list = [_hn_hiring(keywords), _remoteok(keywords)]
    if tavily_api_key:
        tasks.append(_tavily_jobs(tavily_api_key))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_jobs: list[dict] = []
    for r in results:
        if not isinstance(r, Exception):
            all_jobs.extend(r)

    saved_urls = get_saved_urls()
    saved_ct = get_saved_company_titles()
    unique = _dedupe(all_jobs, saved_urls, saved_ct)
    filtered = filter_jobs(unique)

    for job in filtered:
        job["score"], _ = score_job(job)

    filtered.sort(key=lambda j: j.get("score", 0), reverse=True)

    return [
        {
            "company": j.get("company", ""),
            "title": j.get("title", ""),
            "location": j.get("location", ""),
            "url": j.get("url", ""),
            "summary": j.get("summary", ""),
            "source": j.get("source", ""),
            "score": j.get("score", 0),
            "age_days": j.get("age_days", -1),
        }
        for j in filtered[:TOP_JOBS]
    ]


async def extract_requirements(url: str, firecrawl_api_key: str = "") -> dict:
    if firecrawl_api_key:
        content = await _firecrawl(url, firecrawl_api_key)
    else:
        content = await _scrape_simple(url)

    if not content:
        return {"error": "could not fetch page", "url": url}

    return _parse_requirements(content)
