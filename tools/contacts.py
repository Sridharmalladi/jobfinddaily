import hashlib
import re

import httpx

from tools.storage import CACHE_TTL_CONTACTS, get_cache, set_cache

TAVILY_URL = "https://api.tavily.com/search"

_LINKEDIN_RE = re.compile(r"linkedin\.com/in/([\w\-]+)", re.IGNORECASE)
_ROLE_RE = re.compile(
    r"\b(founder|co.?founder|ceo|chief\s+executive|cto|chief\s+technology|"
    r"vp\s+of\s+engineering|head\s+of\s+engineering|engineering\s+manager|"
    r"engineering\s+lead|recruiter|talent\s+partner|hiring\s+manager)\b",
    re.IGNORECASE,
)
# Strip LinkedIn trailing suffix from page title
_STRIP_SUFFIX = re.compile(
    r"\s*[-|–—]\s*(LinkedIn|Profile|LinkedIn Profile).*$", re.IGNORECASE
)
_STRIP_ROLE_SUFFIX = re.compile(
    r"\s*[-|–—]\s*(founder|ceo|cto|recruiter|engineer|manager).*$", re.IGNORECASE
)


def _key(*parts: str) -> str:
    return hashlib.md5("|".join(parts).encode()).hexdigest()


def _extract_linkedin(text: str) -> str:
    m = _LINKEDIN_RE.search(text)
    return f"https://www.linkedin.com/in/{m.group(1)}" if m else ""


def _extract_role(text: str) -> str:
    m = _ROLE_RE.search(text)
    return m.group(0).title() if m else ""


def _clean_name(title: str) -> str:
    name = _STRIP_SUFFIX.sub("", title)
    name = _STRIP_ROLE_SUFFIX.sub("", name)
    return name.strip()


async def find_hiring_people(company: str, api_key: str) -> dict:
    if not api_key:
        return {"contacts": [], "note": "TAVILY_API_KEY not configured"}

    ck = _key("contacts", company.lower())
    if (c := get_cache(ck)) is not None:
        return c

    queries = [
        f'{company} founder OR CEO OR CTO site:linkedin.com',
        f'{company} head of engineering OR recruiter site:linkedin.com',
        f'{company} founder engineer hiring',
    ]

    contacts: list[dict] = []
    seen: set[str] = set()

    async with httpx.AsyncClient(timeout=15) as client:
        for query in queries:
            try:
                resp = await client.post(
                    TAVILY_URL,
                    json={"api_key": api_key, "query": query, "max_results": 5,
                          "search_depth": "basic", "include_answer": False},
                )
                resp.raise_for_status()
            except httpx.HTTPError:
                continue

            for r in resp.json().get("results", []):
                url = r.get("url", "")
                title = r.get("title", "")
                snippet = r.get("content", "")
                full = f"{title} {snippet}"

                role = _extract_role(full)
                if not role:
                    continue

                linkedin = _extract_linkedin(url) or _extract_linkedin(full)
                name = _clean_name(title)

                if not name or name.lower() in seen:
                    continue

                seen.add(name.lower())
                contacts.append({"name": name, "role": role, "linkedin": linkedin})

                if len(contacts) >= 5:
                    break

            if len(contacts) >= 5:
                break

    result: dict = {"contacts": contacts}
    set_cache(ck, result, ttl=CACHE_TTL_CONTACTS)
    return result
