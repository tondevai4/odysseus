import re


# ---------------------------------------------------------------------------
# Thinking / reasoning block stripping
# ---------------------------------------------------------------------------

def strip_thinking(text):
    """Strip thinking / reasoning patterns from LLM output.

    Delegates to `src.text_helpers.strip_think` (single source of truth).
    Kept as an alias here so existing `from src.research_utils import strip_thinking`
    callers don't break. Preserves None passthrough — many callers pass an
    `Optional[str]` LLM result and expect None back when the call failed.
    """
    if text is None:
        return None
    from src.text_helpers import strip_think
    return strip_think(text, prose=False, prompt_echo=True)


# ---------------------------------------------------------------------------
# Source quality filtering & zero-cost pre-filtering
# ---------------------------------------------------------------------------

LOW_QUALITY_MARKERS = [
    "insufficient to",
    "content is insufficient",
    "no substantive data",
    "does not contain",
    "does not provide",
    "does not offer",
    "does not mention",
    "does not discuss",
    "not relevant to",
    "no relevant information",
    "no information",
    "unable to extract",
    "unable to find",
    "completely unrelated",
    "not related to",
    "unrelated to the",
    "boilerplate",
    "footer text",
    "cookie consent",
    "cookie banner",
    "cookie notice",
    "copyright notice",
    "copyright footer",
    "all rights reserved",
    "please enable javascript",
    "enable javascript to run",
    "enable cookies",
    "access denied",
    "403 forbidden",
    "404 not found",
    "page not found",
    "robot check",
    "security verification",
    "cloudflare",
    "verify you are human",
    "just a moment...",
    "attention required",
    "sign in to continue",
    "log in to view",
    "subscription required",
    "paywall",
]


def is_low_quality(summary: str) -> bool:
    """Check if a finding summary or extracted text indicates useless/irrelevant content."""
    try:
        if not isinstance(summary, str) or not summary.strip():
            return True
        low = summary.lower()
        if len(low.strip()) < 30:
            return True
        return any(marker in low for marker in LOW_QUALITY_MARKERS)
    except Exception:
        return False


def heuristic_relevance_check(content: str, query: str) -> bool:
    """Zero-cost pre-filter before calling LLM. Returns False if page is obviously useless.

    Checks:
    - Minimum length
    - Not just error/cookie text
    - Keyword co-occurrence with the research query
    """
    if not content or not isinstance(content, str):
        return False
    text = content.strip()
    if len(text) < 60:
        return False

    low_text = text.lower()
    # Check for blocking/captcha pages
    blocking_phrases = [
        "access denied", "403 forbidden", "enable javascript", "cloudflare",
        "verify you are a human", "robot check", "just a moment..."
    ]
    if any(bp in low_text[:500] for bp in blocking_phrases):
        return False

    # Extract search tokens from query (ignoring generic stopwords)
    stop_words = {
        "a", "an", "the", "and", "or", "of", "in", "on", "at", "to", "for", "with",
        "about", "what", "is", "how", "why", "who", "which", "where", "when",
        "can", "could", "should", "would", "do", "does", "did", "are", "was",
        "were", "be", "been", "being", "have", "has", "had", "i", "you", "my",
        "evaluation", "overview", "analysis", "potential", "study"
    }
    words = [w for w in re.findall(r"[a-z0-9]+", (query or "").lower()) if len(w) >= 3 and w not in stop_words]
    if not words:
        return True  # If query has no distinctive words, allow

    # Require at least one distinctive query term or strong term overlap
    match_count = sum(1 for w in words if w in low_text)
    return match_count >= 1


def clean_web_content(content: str, max_chars: int = 12000) -> str:
    """Clean and normalize extracted web text, preserving logical paragraph structure."""
    if not content or not isinstance(content, str):
        return ""
    # Strip HTML remnants if any
    text = re.sub(r"<script[\s\S]*?</script>", "", content, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", "", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    # Normalize excess blank lines and spaces
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    clean_text = "\n".join(l for l in lines if l)
    if len(clean_text) <= max_chars:
        return clean_text
    truncated = clean_text[:max_chars]
    last_para = truncated.rfind("\n\n")
    if last_para > max_chars * 0.8:
        return truncated[:last_para]
    return truncated
