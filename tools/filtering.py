import re

REJECT_TITLE = re.compile(
    r"\b(senior|sr\.?|staff|lead|principal|director|vp|vice\s+president|"
    r"head\s+of|manager|architect|distinguished|fellow|consultant)\b",
    re.IGNORECASE,
)

NON_TECH_ROLE = re.compile(
    r"\b(sales|revenue\s+cycle|business\s+development|bdr|sdr|"
    r"account\s+executive|account\s+manager|marketing|recruiter|recruiting|"
    r"human\s+resources|paralegal|attorney|lawyer|accountant|finance|"
    r"appointment\s+setter|customer\s+success|customer\s+support|"
    r"payroll|compliance\s+specialist|content\s+writer|copywriter|"
    r"graphic\s+designer|chief\s+revenue|operations\s+specialist)\b",
    re.IGNORECASE,
)

TECH_TITLE = re.compile(
    r"\b(engineer|scientist|researcher|developer|programmer|"
    r"analyst|intern|ml|ai|llm|nlp|data|applied|platform|"
    r"fullstack|full.stack|swe|sde)\b",
    re.IGNORECASE,
)

# Kept for scoring.py imports — not used as the primary filter gate anymore
AI_SIGNAL = re.compile(
    r"\b(ai|ml|llm|machine\s+learning|deep\s+learning|nlp|computer\s+vision|"
    r"neural|rag|embedding|vector|transformer|gpt|claude|langchain|llamaindex|"
    r"agent|generative|diffusion|reinforcement\s+learning|data\s+science|"
    r"applied\s+scientist|research\s+engineer)\b",
    re.IGNORECASE,
)

ENTERPRISE_SIGNAL = re.compile(
    r"\b(deloitte|accenture|mckinsey|pwc|kpmg|bcg|bain|booz|big\s*4|"
    r"fortune\s+500|government\s+contract|federal|defense\s+contractor)\b",
    re.IGNORECASE,
)

PURE_ANALYST = re.compile(
    r"\b(business\s+analyst|bi\s+analyst|marketing\s+analyst|"
    r"financial\s+analyst|product\s+analyst)\b",
    re.IGNORECASE,
)

EXPERIENCE_YEARS = re.compile(
    r"(\d+)\+?\s*(?:–|-|to)?\s*(\d+)?\s*years?\s+(?:of\s+)?(?:professional\s+|relevant\s+)?experience",
    re.IGNORECASE,
)

# Specific technical terms that only appear in real ML/LLM engineering roles.
# Generic words like "AI" and "ML" are intentionally excluded.
STRONG_TECH_SIGNALS = [
    # Model training & tuning
    "fine-tun", "finetuning", "fine tuning", "rlhf", "rlaif",
    "lora", "qlora", "peft", "sft", "instruction tuning",
    "pretraining", "pre-training",
    # RAG & retrieval
    "rag", "retrieval augmented", "vector database", "vector store",
    "embedding model", "semantic search", "hybrid search",
    # Vector DBs
    "pinecone", "chromadb", "weaviate", "qdrant", "faiss", "milvus",
    # LLM frameworks
    "langchain", "llamaindex", "langgraph", "haystack", "dspy",
    "huggingface", "hugging face", "transformers",
    # Agentic frameworks (2024-2025 wave)
    "crewai", "crew ai", "autogen", "auto-gen", "pydantic ai", "pydantic-ai",
    "smolagents", "instructor", "guardrails", "agno", "composio",
    "e2b sandbox", "mem0", "phidata",
    # Local / serving
    "vllm", "llama.cpp", "gguf", "ggml", "ollama", "mlx",
    "local inference", "model serving", "model deployment",
    "triton inference", "tgi ", "text generation inference",
    # Training infra
    "distributed training", "cuda", "gpu cluster", "deepspeed",
    "fsdp", "megatron", "a100", "h100",
    # AI agents
    "ai agent", "agentic", "autonomous agent", "tool use",
    "function calling", "multi-agent", "agent framework",
    # APIs / foundation models
    "openai api", "anthropic api", "claude api", "gpt-4", "gpt4",
    "gemini api", "mistral", "llama 3", "llama3",
    # MLOps
    "mlops", "ml platform", "mlflow", "wandb", "weights & biases",
    "model registry", "feature store", "data pipeline for ml",
    # Specific disciplines
    "computer vision", "natural language processing",
    "multimodal", "diffusion model", "stable diffusion",
    "reinforcement learning", "reward model",
    # PyTorch / frameworks (specific enough)
    "pytorch", "tensorflow", "jax/flax", "jax ",
]

MIN_STRONG_SIGNALS = 1


def _count_strong_signals(text: str) -> int:
    cl = text.lower()
    return sum(1 for kw in STRONG_TECH_SIGNALS if kw in cl)


def _max_experience_required(text: str) -> int:
    years = []
    for m in EXPERIENCE_YEARS.finditer(text):
        years.append(int(m.group(1)))
        if m.group(2):
            years.append(int(m.group(2)))
    return max(years) if years else 0


def filter_job(job: dict) -> tuple[bool, str]:
    """Returns (keep, reject_reason). Deterministic — no LLM."""
    title = job.get("title", "")
    desc = job.get("description", "") or job.get("summary", "")
    full = f"{title} {desc}"

    if REJECT_TITLE.search(title):
        return False, "senior/staff/lead title"

    if NON_TECH_ROLE.search(title):
        return False, "non-technical role"

    if not TECH_TITLE.search(title):
        return False, "no technical role in title"

    strong_count = _count_strong_signals(full)
    if strong_count < MIN_STRONG_SIGNALS:
        return False, f"only {strong_count}/{MIN_STRONG_SIGNALS} required tech signals"

    if ENTERPRISE_SIGNAL.search(full):
        return False, "enterprise/consulting firm"

    if PURE_ANALYST.search(title) and not AI_SIGNAL.search(title):
        return False, "pure analyst role"

    max_exp = _max_experience_required(desc)
    if max_exp >= 3:
        return False, f"requires {max_exp}+ years experience"

    return True, ""


def filter_jobs(jobs: list[dict]) -> list[dict]:
    return [j for j in jobs if filter_job(j)[0]]
