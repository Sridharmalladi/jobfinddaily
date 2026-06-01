import re
from tools.filtering import AI_SIGNAL, REJECT_TITLE, ENTERPRISE_SIGNAL, PURE_ANALYST

STRONG_AI = re.compile(
    r"\b(llm|rag|agent|langchain|llamaindex|langgraph|crewai|autogen|"
    r"pydantic.?ai|smolagents|embedding|vector\s*db|pinecone|"
    r"chroma|weaviate|openai|anthropic|fine.?tun|generative\s+ai|"
    r"ml\s+platform|mlops|multimodal|diffusion|transformer)\b",
    re.IGNORECASE,
)

STARTUP_SIGNAL = re.compile(
    r"\b(startup|seed|series\s+[ab]|yc|y\s+combinator|early.stage|"
    r"founding\s+engineer|founding\s+member|fast.moving|scrappy|"
    r"pre.seed|early\s+employee|small\s+team)\b",
    re.IGNORECASE,
)

REMOTE_SIGNAL = re.compile(
    r"\b(remote|work\s+from\s+home|wfh|distributed|anywhere)\b",
    re.IGNORECASE,
)

JUNIOR_SIGNAL = re.compile(
    r"\b(0[-–]2|1[-–]2|entry.?level|junior|new\s+grad|recent\s+grad|"
    r"no\s+experience\s+required|internship|intern|0\+\s*year|1\+\s*year)\b",
    re.IGNORECASE,
)

BUILDER_SIGNAL = re.compile(
    r"\b(builder|ship|deploy|production|real.world|pragmatic|"
    r"move\s+fast|iteration|product.minded|full.stack\s+ai|ownership|impact)\b",
    re.IGNORECASE,
)

PURE_BACKEND = re.compile(
    r"\b(backend|back.end|infrastructure|devops|sre|platform\s+engineer)\b",
    re.IGNORECASE,
)

# AI Engineer title preference (application layer > pure research)
AI_ENG_TITLE = re.compile(
    r"\b(ai\s+engineer|llm\s+engineer|ai\s+application|founding\s+ai|"
    r"applied\s+ai\s+engineer|ai\s+product\s+engineer|full.?stack\s+ai)\b",
    re.IGNORECASE,
)

# Visa / work authorization signals
VISA_BOOST = re.compile(
    r"\b(visa\s+sponsor|h.?1.?b\s+sponsor|opt\s+eligible|opt\s+sponsor|"
    r"work\s+authorization\s+provided|sponsorship\s+available|we\s+sponsor|"
    r"will\s+sponsor|open\s+to\s+sponsoring)\b",
    re.IGNORECASE,
)
NO_SPONSOR = re.compile(
    r"\b(no\s+(?:visa\s+)?sponsorship|no\s+h.?1.?b|cannot\s+sponsor|"
    r"will\s+not\s+sponsor|us\s+citizen(?:s)?\s+only|green\s+card\s+only|"
    r"must\s+be\s+(?:a\s+)?(?:us\s+)?citizen|authorized\s+to\s+work\s+without\s+sponsorship)\b",
    re.IGNORECASE,
)

# Contract / short-term roles are a positive signal
CONTRACT_SIGNAL = re.compile(
    r"\b(contract(?:\s+role|\s+position)?|freelance|short.?term|"
    r"contract.?to.?hire|1099|c2c|corp.?to.?corp|"
    r"\d+.month\s+contract|\d+.month\s+engagement)\b",
    re.IGNORECASE,
)

# US location signals
US_SIGNAL = re.compile(
    r"\b(united\s+states|us\s+remote|u\.s\.\s+remote|us\s+only|"
    r"u\.s\.\s+only|americas|north\s+america)\b",
    re.IGNORECASE,
)
NON_US_ONLY = re.compile(
    r"\b(uk\s+only|europe\s+only|eu\s+only|apac\s+only|"
    r"australia\s+only|canada\s+only|germany\s+only|uk\s+based)\b",
    re.IGNORECASE,
)

MAX_AGE_DAYS = 60


def score_job(job: dict) -> tuple[int, list[str]]:
    title = job.get("title", "")
    desc = job.get("description", "") or job.get("summary", "")
    location = job.get("location", "")
    age_days = job.get("age_days", -1)
    full = f"{title} {desc} {location}"

    score = 0
    reasons: list[str] = []

    # ── Core AI/ML quality ────────────────────────────────────────────────────
    if STRONG_AI.search(full):
        score += 20
        reasons.append("+20 strong LLM/RAG/agent signal")

    if AI_ENG_TITLE.search(title):
        score += 12
        reasons.append("+12 AI Engineer title (application layer)")

    # ── Startup fit ───────────────────────────────────────────────────────────
    if STARTUP_SIGNAL.search(full):
        score += 20
        reasons.append("+20 startup / small-team signal")

    if REMOTE_SIGNAL.search(full):
        score += 15
        reasons.append("+15 remote")

    if JUNIOR_SIGNAL.search(full):
        score += 15
        reasons.append("+15 junior / entry-level / internship")

    if AI_SIGNAL.search(job.get("company", "") + " " + desc):
        score += 10
        reasons.append("+10 AI-focused company")

    if BUILDER_SIGNAL.search(full):
        score += 10
        reasons.append("+10 practical builder culture")

    # ── Contract / flexible roles ─────────────────────────────────────────────
    if CONTRACT_SIGNAL.search(full):
        score += 12
        reasons.append("+12 contract / short-term role")

    # ── Visa / work authorization ─────────────────────────────────────────────
    if VISA_BOOST.search(full):
        score += 15
        reasons.append("+15 visa / OPT sponsorship offered")

    if NO_SPONSOR.search(full):
        score -= 30
        reasons.append("-30 no visa sponsorship")

    # ── US location ───────────────────────────────────────────────────────────
    if US_SIGNAL.search(full):
        score += 10
        reasons.append("+10 US-based or US remote")

    if NON_US_ONLY.search(full):
        score -= 20
        reasons.append("-20 non-US only role")

    # ── Freshness ─────────────────────────────────────────────────────────────
    if age_days != -1:
        if age_days > 90:
            score -= 40
            reasons.append(f"-40 stale listing ({age_days}d old)")
        elif age_days > MAX_AGE_DAYS:
            score -= 20
            reasons.append(f"-20 older listing ({age_days}d old)")
        elif age_days <= 7:
            score += 8
            reasons.append(f"+8 fresh listing ({age_days}d old)")

    # ── Penalties ─────────────────────────────────────────────────────────────
    if REJECT_TITLE.search(title):
        score -= 25
        reasons.append("-25 senior/staff/lead title")

    if ENTERPRISE_SIGNAL.search(full):
        score -= 20
        reasons.append("-20 enterprise/consulting")

    if PURE_BACKEND.search(title) and not AI_SIGNAL.search(full):
        score -= 15
        reasons.append("-15 pure backend without AI")

    if PURE_ANALYST.search(title) and not AI_SIGNAL.search(full):
        score -= 15
        reasons.append("-15 pure analyst without ML")

    return score, reasons


def score_jobs(jobs: list[dict]) -> list[dict]:
    ranked = []
    for job in jobs:
        score, reasons = score_job(job)
        ranked.append({"job": job, "score": score, "reasons": reasons})
    return sorted(ranked, key=lambda x: x["score"], reverse=True)
