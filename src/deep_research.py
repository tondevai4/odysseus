# src/deep_research.py
"""
State-of-the-Art Deep Research Engine.

Implements an iterative, cost-efficient Plan -> Target-Query -> 0-Cost-Filter -> Extract -> Progressive-Synthesize loop.
Designed for maximum information density, zero hallucinated URLs, high factual precision, and resilient error recovery.
"""
import asyncio
import json
import logging
import re
import time
from datetime import datetime
from typing import Callable, Dict, List, Optional, Set

from src.research_utils import (
    strip_thinking,
    is_low_quality,
    heuristic_relevance_check,
    clean_web_content,
)
from src.goal_based_extractor import EXTRACTOR_SYSTEM
from src.prompt_security import untrusted_context_message

logger = logging.getLogger(__name__)


def current_date_context() -> str:
    """Preamble that grounds query-generation/planning LLMs in the real current date."""
    now = datetime.now().astimezone()
    return (
        f"Today's date is {now.strftime('%B %d, %Y')} ({now.strftime('%Y-%m-%d')}). "
        f"When a search query needs a year or refers to 'latest'/'current'/'this year', "
        f"use {now.strftime('%Y')} or relative wording -- never infer outdated years from training data.\n\n"
    )


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------
RESEARCH_PLAN_PROMPT = """\
You are a senior research analyst and strategist.
Deconstruct this research question into a comprehensive, multi-dimensional research strategy:

**Research Question:** {question}

Analyze and break this down across 4 core pillars:
1. **Core Subject & Fundamentals**: What are the essential facts, definitions, or foundational mechanics?
2. **Market & Data**: What concrete statistics, pricing, financials, market sizes, or metrics must be discovered?
3. **Competitive Landscape & Alternatives**: Who are the major players, competing models, or benchmark solutions?
4. **Risks, Friction & Counter-arguments**: What are the critical challenges, hidden costs, failure modes, or opposing views?

Return ONLY a JSON object with:
{{
  "sub_questions": [
    "Specific question on fundamentals",
    "Specific question on market data/numbers",
    "Specific question on competitors/alternatives",
    "Specific question on risks/challenges"
  ],
  "key_dimensions": ["fundamentals", "financials_and_metrics", "competitive_landscape", "risks_and_challenges"],
  "target_data_points": ["pricing", "market size", "key competitors", "failure factors"],
  "success_criteria": "A thorough, data-backed briefing answering the question with verified facts and comparative analysis."
}}
"""

QUERY_GEN_PROMPT = """\
You are an expert web research query strategist.

**Goal:** {question}

**Research Strategy:**
{research_plan}

**What we have already verified:**
{report}

**Current Round:** {round_num} of {max_rounds}
{round_instruction}

Generate {num_queries} highly targeted, distinct search queries.
Guidelines:
- Use specific industry keywords, technical terminology, or quoted phrases where precision is needed.
- Target different dimensions (e.g. market data, pricing, competitor comparison, reviews/complaints).
- Avoid overly long sentence queries; write queries optimized for modern search engines.

Return ONLY a JSON array of query strings:
["query 1", "query 2", "query 3"]
"""

SYNTHESIZE_PROMPT = """\
You are a senior intelligence analyst updating an evolving research knowledge base.

**Research Goal:** {question}

**Current Working Knowledge:**
{report}

**New Verified Evidence Gathered This Round:**
{new_findings}

Task:
Synthesize the new verified findings into the working knowledge base.
1. Integrate new facts, data points, statistics, dates, and quotes under logical topic headers.
2. Remove any redundancy or contradictory outdated claims.
3. Maintain precise inline citations using markdown links: [Source Name or Domain](url).
4. Emphasize hard data, numbers, comparisons, and strategic context.

Write ONLY the updated structured markdown knowledge base -- no conversational preamble.
"""

STOP_PROMPT = """\
You are the research director deciding whether we have sufficient high-quality evidence.

**Research Goal:** {question}

**Current Synthesized Evidence:**
{report}

**Round:** {round_num} of {max_rounds}

Evaluate coverage:
- Are all key dimensions (overview, data/financials, competitors, risks) addressed with real evidence?
- Do we have specific data points and multiple distinct sources?
- Are there still critical gaps or unanswered sub-questions?

Respond with ONLY "YES" or "NO" followed by a concise 1-sentence reason:
Example: "YES -- We have collected verified data across market size, competitors, and risk factors from 8 distinct sources."
Example: "NO -- We still lack verified pricing information and direct competitor comparison data."
"""

FINAL_REPORT_PROMPT = """\
You are a world-class investigative analyst and industry briefing author.
Write a **definitive, publication-grade research report** answering this question based on all collected evidence:

**Research Goal:** {question}

**Synthesized Evidence & Source Knowledge:**
{report}

---

### REQUIRED REPORT STRUCTURE:

# {question}

## Executive Summary
Provide a high-impact overview (2-3 paragraphs) synthesizing the core answer, key findings, and bottom-line takeaway.

> ### Key Insights & Strategic Highlights
> - **[Key Finding 1]**: Concrete takeaway with specific numbers/details.
> - **[Key Finding 2]**: Critical data point or market reality.
> - **[Key Finding 3]**: Competitive or strategic differentiator.
> - **[Key Finding 4]**: Primary risk factor or execution challenge.

## 1. Landscape & Core Fundamentals
Comprehensive breakdown of the subject, background context, key definitions, and the current state of the art. Include verified citations [Source](url).

## 2. Competitive Landscape & Comparative Analysis
Analyze the major players, products, or alternatives.
Include a detailed **Markdown Comparison Table** (columns such as Entity/Option, Key Strengths, Weaknesses, Pricing/Model, Verdict).

## 3. Data, Financials & Market Metrics
Detail specific numbers, market sizes, costs, revenue models, pricing tiers, unit economics, or quantitative findings gathered from the research.

## 4. Critical Challenges, Risks & Failure Modes
Honest, objective analysis of the primary risks, operational hurdles, common mistakes, regulatory issues, or counter-arguments.

## 5. Strategic Verdict & Actionable Roadmap
Provide a definitive conclusion directly answering the user's question, accompanied by actionable recommendations and next steps.

## References & Verified Sources
List all referenced sources as bullet points with clickable markdown links:
- [Source Title](URL) -- Key contribution from this source

---
STYLE REQUIREMENTS:
- Minimum 1,200 - 1,800 words.
- Maintain high factual density -- prioritize specific names, numbers, dates, and concrete evidence over generic filler.
- Use clean Markdown formatting, blockquotes for callouts, and formatted tables.
- Every major claim must reference its source URL inline as [Source Name](url).
"""

CATEGORY_PROMPTS = {
    "product": """IMPORTANT FORMAT OVERRIDE -- PRODUCT & MARKET EVALUATION:
- Structure Section 2 as a Ranked Product Breakdown with ### headers for each product, pros/cons bullet lists, and pricing.
- Include a quick-reference Feature & Price Comparison Table.
- In Section 5, provide explicit "Best Overall", "Best Value", and "Best for Specific Needs" verdicts.""",

    "comparison": """IMPORTANT FORMAT OVERRIDE -- DIRECT COMPARISON REPORT:
- Ensure Section 2 features an exhaustive Comparison Table comparing all options across key criteria.
- Break down each competitor with deep-dive subsections on Pros, Cons, Unique Advantages, and Pricing.
- Conclude with situational verdicts: "Choose A if...", "Choose B if...""",

    "howto": """IMPORTANT FORMAT OVERRIDE -- HOW-TO & IMPLEMENTATION GUIDE:
- Include a ## Quick Start Summary box at the top (step-by-step 1-line actions).
- Provide detailed, numbered Step-by-Step guides with prerequisites, tips (> **Tip:**), and warnings (> **Warning:**).
- Include a ## Troubleshooting & Common Pitfalls section.""",

    "factcheck": """IMPORTANT FORMAT OVERRIDE -- FACT-CHECK & VERIFICATION:
- Structure as: ## The Core Claims, ## Verified Evidence For, ## Evidence Against, and ## Definitive Verdict (**Supported**, **Mixed**, or **Refuted**).
- Address nuances, context, and conflicting reports rigorously.""",
}


# ---------------------------------------------------------------------------
# DeepResearcher
# ---------------------------------------------------------------------------
class DeepResearcher:
    """
    State-of-the-Art Deep Research Engine.
    Orchestrates iterative plan-driven search, 0-cost pre-filtering, structured extraction,
    progressive synthesis, and publication-grade reporting.
    """

    def __init__(
        self,
        llm_endpoint: str,
        llm_model: str,
        llm_headers: Optional[Dict] = None,
        max_rounds: int = 6,
        max_time: int = 300,
        max_urls_per_round: int = 4,
        max_content_chars: int = 12000,
        max_report_tokens: int = 8192,
        extraction_timeout: int = 60,
        planning_timeout: int = 60,
        query_timeout: int = 60,
        extraction_concurrency: int = 4,
        min_rounds: int = 2,
        max_empty_rounds: int = 2,
        synthesis_window: int = 12,
        progress_callback: Optional[Callable] = None,
        search_provider: Optional[str] = None,
        category: Optional[str] = None,
    ):
        self.llm_endpoint = llm_endpoint
        self.llm_model = llm_model
        self.llm_headers = llm_headers
        self.search_provider_override = search_provider
        self.category = category
        self.max_rounds = min(12, max(1, int(max_rounds or 6)))
        self.max_time = max(60, int(max_time or 300))
        self.max_urls_per_round = max_urls_per_round
        self.max_content_chars = max_content_chars
        self.max_report_tokens = max_report_tokens
        self.extraction_timeout = min(180, max(15, int(extraction_timeout or 60)))
        self.planning_timeout = min(180, max(15, int(planning_timeout or 60)))
        self.query_timeout = min(180, max(15, int(query_timeout or 60)))
        self.extraction_concurrency = min(8, max(1, int(extraction_concurrency or 4)))
        self.min_rounds = min_rounds
        self.max_empty_rounds = max_empty_rounds
        self.synthesis_window = synthesis_window
        self._progress = progress_callback
        self._cancelled = False
        self._start_time: float = 0
        self.queries_used: Set[str] = set()
        self.urls_fetched: Set[str] = set()
        self.analyzed_urls: List[Dict[str, str]] = []
        self.round_count: int = 0
        self.providers_used: List[str] = []
        self.findings: List[Dict] = []
        self.evolving_report: str = ""
        self.research_plan: str = ""

    def cancel(self):
        """Cooperative cancellation flag."""
        self._cancelled = True

    async def research(
        self,
        question: str,
        prior_report: str = "",
        prior_findings: Optional[List[Dict]] = None,
        prior_urls: Optional[Set[str]] = None,
    ) -> str:
        """Execute SOTA deep research and produce a publication-grade report."""
        self._start_time = time.time()
        findings: List[Dict] = list(prior_findings) if prior_findings else []
        report = prior_report or ""

        # Step 1: Strategic Dimension Planning
        self._emit(phase="planning", message="Analyzing research dimensions and strategy...")
        self.research_plan = await self._create_plan(question)
        logger.info(f"Research plan formulated: {self.research_plan[:160]}")

        # Auto-detect category if not pinned
        if not self.category and not prior_report:
            self.category = await self._classify_category(question)
            if self.category:
                logger.info(f"Auto-classified category: {self.category}")

        if prior_urls:
            self.urls_fetched.update(prior_urls)
        self.findings = findings
        consecutive_empty_rounds = 0

        # Step 2: Iterative Deep Research Rounds
        for round_num in range(1, self.max_rounds + 1):
            self.round_count = round_num
            if self._cancelled:
                logger.info(f"Research cancelled at round {round_num}")
                break
            if self._time_exceeded():
                logger.info(f"Research time limit reached at round {round_num}")
                break

            logger.info(f"=== Research Round {round_num}/{self.max_rounds} ===")
            self._emit(phase="searching", round=round_num, total_sources=len(self.urls_fetched))

            # Generate targeted queries for this round
            queries = await self._generate_queries(question, report, round_num)
            if not queries:
                logger.warning(f"Round {round_num}: No queries generated, breaking early")
                break

            self._emit(
                phase="searching",
                round=round_num,
                queries=len(queries),
                query_preview=queries[0] if queries else "",
                total_sources=len(self.urls_fetched),
            )

            # Search, 0-Cost pre-filter & extract
            round_findings = await self._search_and_extract(queries, question)
            if round_findings:
                findings.extend(round_findings)
                consecutive_empty_rounds = 0
                logger.info(f"Round {round_num}: extracted {len(round_findings)} verified findings (total: {len(findings)})")
                self._emit(
                    phase="reading",
                    round=round_num,
                    new_sources=len(round_findings),
                    total_sources=len(self.urls_fetched),
                    total_findings=len(findings),
                )
            else:
                consecutive_empty_rounds += 1
                logger.info(f"Round {round_num}: 0 verified findings ({consecutive_empty_rounds} consecutive empty)")
                if consecutive_empty_rounds >= self.max_empty_rounds:
                    err_detail = getattr(self, "_last_search_error", "No search results returned")
                    logger.warning(f"Search provider exhausted: {err_detail}")
                    if not findings:
                        return (
                            f"**Research Search Unavailable** -- Could not retrieve web results after {round_num} rounds.\n\n"
                            f"Detail: `{err_detail}`\n\nPlease check your configured search provider in Settings."
                        )
                    break

            # Synthesize progressive knowledge ledger
            if findings:
                self._emit(
                    phase="analyzing",
                    round=round_num,
                    total_sources=len(self.urls_fetched),
                    total_findings=len(findings),
                )
                report = await self._synthesize(question, findings, report)
                self.evolving_report = report

            # Decide whether research coverage is comprehensive
            if round_num >= self.min_rounds:
                should_stop = await self._should_stop(question, report, round_num)
                if should_stop:
                    logger.info(f"Research engine concluded comprehensive coverage at round {round_num}")
                    break

        # Step 3: Master Editorial Synthesis
        self._emit(
            phase="writing",
            message="Composing publication-grade briefing...",
            total_sources=len(self.urls_fetched),
            total_findings=len(findings),
        )

        if not report and not findings:
            return "No verifiable information could be gathered for this research question."

        # Compile final master report
        final_report = await self._final_report(question, report or self._format_findings(findings))
        elapsed = time.time() - self._start_time
        logger.info(
            f"Research complete: {self.round_count} rounds, "
            f"{len(findings)} findings, {len(self.urls_fetched)} URLs, {elapsed:.1f}s"
        )
        return final_report

    # ------------------------------------------------------------------
    # LLM Helper
    # ------------------------------------------------------------------
    async def _llm(
        self,
        messages: List[Dict],
        temperature: float = 0.2,
        max_tokens: int = 4096,
        timeout: int = 60,
    ) -> str:
        """Call LLM endpoint and clean thinking blocks."""
        from src.llm_core import llm_call_async
        response = await llm_call_async(
            url=self.llm_endpoint,
            model=self.llm_model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            headers=self.llm_headers,
            timeout=timeout,
        )
        return strip_thinking(response) or ""

    # ------------------------------------------------------------------
    # Strategic Dimension Planning
    # ------------------------------------------------------------------
    async def _create_plan(self, question: str) -> str:
        """Formulate a 4-pillar research strategy."""
        prompt = current_date_context() + RESEARCH_PLAN_PROMPT.format(question=question)
        try:
            response = await self._llm(
                [{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=1024,
                timeout=self.planning_timeout,
            )
            parsed = self._parse_json_object(response)
            if parsed and isinstance(parsed, dict):
                parts = []
                if parsed.get("sub_questions"):
                    parts.append("Key Dimensions:\n" + "\n".join(f"- {q}" for q in parsed["sub_questions"]))
                if parsed.get("target_data_points"):
                    parts.append("Target Data: " + ", ".join(parsed["target_data_points"]))
                if parsed.get("success_criteria"):
                    parts.append("Objective: " + parsed["success_criteria"])
                return "\n\n".join(parts) if parts else response
            return response
        except Exception as e:
            logger.warning(f"Research plan formulation failed: {e}")
            return f"Investigate all key facets, data points, competitors, and risk factors for: {question}"

    async def _classify_category(self, question: str) -> Optional[str]:
        """Classify research intent into optimal editorial template."""
        valid = ", ".join(CATEGORY_PROMPTS.keys())
        prompt = (
            f"Classify this research question into exactly ONE category: {valid}\n"
            f"If none fit, reply with 'general'.\n\nQuestion: {question}\n\nReply with ONLY the word."
        )
        try:
            result = await self._llm([{"role": "user", "content": prompt}], temperature=0, max_tokens=15, timeout=12)
            cat = (result or "").strip().lower()
            for c in CATEGORY_PROMPTS:
                if c in cat:
                    return c
            return None
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Targeted Query Generation
    # ------------------------------------------------------------------
    async def _generate_queries(self, question: str, report: str, round_num: int) -> List[str]:
        """Generate targeted search queries designed for information density."""
        if round_num == 1:
            num_queries = 4
            round_instruction = (
                "ROUND 1 (Landscape & Core Entities): Generate 4 queries covering "
                "the core subject overview, key definitions, primary players, and industry overview."
            )
        elif round_num == 2:
            num_queries = 3
            round_instruction = (
                "ROUND 2 (Competitive Breakdown & Comparisons): Generate 3 queries targeting "
                "competitor comparisons, benchmark solutions, alternatives, and technical capabilities."
            )
        elif round_num == 3:
            num_queries = 3
            round_instruction = (
                "ROUND 3 (Financials, Data & Metrics): Generate 3 queries targeting "
                "pricing, market size, revenue models, statistics, unit economics, and quantitative data."
            )
        else:
            num_queries = 3
            round_instruction = (
                f"ROUND {round_num} (Risks, Challenges & Evidence Verification): Generate 3 queries targeting "
                "unanswered questions, known complaints, failure modes, regulatory risks, or missing details."
            )

        prompt = current_date_context() + QUERY_GEN_PROMPT.format(
            question=question,
            research_plan=self.research_plan or "Investigate all key dimensions.",
            report=report or "(Initial round -- no data yet)",
            round_num=round_num,
            max_rounds=self.max_rounds,
            num_queries=num_queries,
            round_instruction=round_instruction,
        )

        try:
            response = await self._llm(
                [{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=1024,
                timeout=self.query_timeout,
            )
            queries = self._parse_json_array(response)
            new_queries = [q.strip() for q in queries if q.strip() and q.strip() not in self.queries_used]
            self.queries_used.update(new_queries)
            logger.info(f"Round {round_num} generated queries: {new_queries}")
            return new_queries
        except Exception as e:
            logger.error(f"Query generation error: {e}")
            fallback_q = f"{question} {round_num}"
            if fallback_q not in self.queries_used:
                self.queries_used.add(fallback_q)
                return [fallback_q]
            return []

    # ------------------------------------------------------------------
    # Search + 0-Cost Pre-Filter + Extract
    # ------------------------------------------------------------------
    async def _search_and_extract(self, queries: List[str], question: str) -> List[Dict]:
        """Search in parallel, apply zero-cost pre-filtering, and extract structured facts."""
        search_tasks = [self._search(q) for q in queries]
        search_results = await asyncio.gather(*search_tasks, return_exceptions=True)

        urls_to_fetch = []
        for res in search_results:
            if isinstance(res, Exception) or not res:
                continue
            for item in res:
                url = item.get("url", "")
                if url and url not in self.urls_fetched:
                    urls_to_fetch.append(item)
                    self.urls_fetched.add(url)
                    self.analyzed_urls.append({
                        "url": url,
                        "title": item.get("title", "") or url,
                    })
                if len(urls_to_fetch) >= self.max_urls_per_round * len(queries):
                    break

        if self._cancelled or self._time_exceeded() or not urls_to_fetch:
            return []

        semaphore = asyncio.Semaphore(self.extraction_concurrency)

        async def _bounded_extract(item: Dict) -> Optional[Dict]:
            async with semaphore:
                return await self._fetch_and_extract(item["url"], question, item.get("title", ""))

        extract_tasks = [_bounded_extract(item) for item in urls_to_fetch]
        results_gathered = await asyncio.gather(*extract_tasks, return_exceptions=True)

        valid_findings = []
        for res in results_gathered:
            if isinstance(res, dict) and res.get("summary") and not is_low_quality(res.get("summary", "")):
                valid_findings.append(res)
        return valid_findings

    async def _search(self, query: str) -> List[Dict]:
        """Execute web search with automated provider fallback."""
        try:
            from src.search.providers import _get_search_settings
            from src.search.core import _call_provider, _build_provider_chain

            settings = _get_search_settings()
            provider = (self.search_provider_override or "").strip()
            if not provider:
                provider = (settings.get("research_search_provider") or "").strip()
            if not provider:
                provider = settings.get("search_provider", "searxng")

            if provider == "disabled":
                return []

            chain = _build_provider_chain(provider)
            # Ensure robust fallback providers are present in chain
            for fallback_prov in ("searxng", "duckduckgo", "brave", "tavily"):
                if fallback_prov not in chain:
                    chain.append(fallback_prov)

            for prov in chain:
                try:
                    results = await asyncio.to_thread(_call_provider, prov, query, 8)
                    if results:
                        logger.info(f"Search provider '{prov}' returned {len(results)} hits for '{query[:40]}'")
                        if prov not in self.providers_used:
                            self.providers_used.append(prov)
                        return results
                except Exception as prov_err:
                    logger.debug(f"Provider '{prov}' search failed for '{query[:40]}': {prov_err}")
                    self._last_search_error = f"{prov}: {prov_err}"

            self._last_search_error = f"No search results returned across providers ({', '.join(chain)})"
            return []
        except Exception as e:
            logger.error(f"Search failure: {e}")
            self._last_search_error = str(e)
            return []

    async def _fetch_and_extract(self, url: str, question: str, title: str) -> Optional[Dict]:
        """Scrape webpage, apply 0-cost relevance gate, and extract verified structured facts."""
        display = title or url
        self._emit(phase="reading", url=url, title=display, total_sources=len(self.urls_fetched))

        try:
            from src.search import fetch_webpage_content
            page = await asyncio.to_thread(fetch_webpage_content, url, 10)
        except Exception as e:
            logger.warning(f"Webpage fetch failed for {url}: {e}")
            return None

        if not page or not page.get("success") or not page.get("content"):
            return None

        raw_content = page.get("content", "")

        # -- 0-COST HEURISTIC PRE-FILTER --
        # If the page is obviously off-topic, empty, or a captcha, discard immediately without an LLM call!
        if not heuristic_relevance_check(raw_content, question):
            logger.debug(f"0-Cost filter rejected off-topic/empty page: {url}")
            return None

        cleaned_text = clean_web_content(raw_content, max_chars=self.max_content_chars)
        if len(cleaned_text) < 150:
            return None

        try:
            response = await self._llm(
                [
                    {"role": "user", "content": EXTRACTOR_SYSTEM.format(goal=question)},
                    untrusted_context_message("webpage", cleaned_text),
                ],
                temperature=0.1,
                max_tokens=1500,
                timeout=self.extraction_timeout,
            )

            parsed = self._parse_json_object(response)
            if parsed and isinstance(parsed, dict):
                # Check strict boolean relevance gate
                if parsed.get("relevant") is False:
                    logger.debug(f"LLM extractor flagged page as not relevant: {url}")
                    return None

                summary = parsed.get("summary", "").strip()
                if is_low_quality(summary):
                    return None

                parsed["url"] = url
                parsed["title"] = title or page.get("title", "") or url
                parsed["og_image"] = page.get("og_image", "")
                return parsed

            # Fallback if raw text output
            clean_resp = strip_thinking(response).strip()
            if clean_resp and not is_low_quality(clean_resp) and len(clean_resp) > 50:
                return {
                    "url": url,
                    "title": title or page.get("title", "") or url,
                    "og_image": page.get("og_image", ""),
                    "summary": clean_resp[:600],
                    "evidence": clean_resp[:2000],
                    "rational": "Factual extraction",
                }
            return None
        except Exception as e:
            logger.warning(f"Extraction failed for {url}: {e}")
            return None

    # ------------------------------------------------------------------
    # Progressive Synthesis
    # ------------------------------------------------------------------
    async def _synthesize(self, question: str, findings: List[Dict], current_report: str) -> str:
        """Progressively merge verified facts into the evolving knowledge base."""
        window = findings[-self.synthesis_window:]
        findings_text = self._format_findings(window)

        prompt = SYNTHESIZE_PROMPT.format(
            question=question,
            report=current_report or "(First round -- initializing structured knowledge base)",
            new_findings=findings_text,
        )

        try:
            updated = await self._llm(
                [{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=self.max_report_tokens,
                timeout=120,
            )
            if updated and len(updated.strip()) > 100:
                return updated.strip()
            return current_report or self._format_findings(findings)
        except Exception as e:
            logger.error(f"Synthesis step failed: {e}")
            return current_report or self._format_findings(findings)

    # ------------------------------------------------------------------
    # Coverage Decision
    # ------------------------------------------------------------------
    async def _should_stop(self, question: str, report: str, round_num: int) -> bool:
        """Decide if research depth is complete."""
        prompt = STOP_PROMPT.format(
            question=question,
            report=report[:6000],
            round_num=round_num,
            max_rounds=self.max_rounds,
        )
        try:
            response = await self._llm([{"role": "user", "content": prompt}], temperature=0.1, max_tokens=100, timeout=30)
            clean = strip_thinking(response).strip()
            answer = re.sub(r"^[\s*_`\"'>#\-]+", "", clean).upper()
            should_stop = answer.startswith("YES")
            logger.info(f"Stop evaluation (round {round_num}): {clean[:100]}")
            return should_stop
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Master Editorial Report
    # ------------------------------------------------------------------
    async def _final_report(self, question: str, report: str) -> str:
        """Generate the publication-grade final research briefing."""
        prompt = FINAL_REPORT_PROMPT.format(
            question=question,
            report=report,
        )
        cat_extra = CATEGORY_PROMPTS.get(self.category or "", "")
        if cat_extra:
            prompt += "\n\n" + cat_extra

        try:
            result = await self._llm(
                [{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=self.max_report_tokens,
                timeout=180,
            )
            if result and len(result.split()) >= 300:
                return result.strip()
            return report
        except Exception as e:
            logger.error(f"Final master report composition failed: {e}")
            return report

    # ------------------------------------------------------------------
    # Utilities & Parsers
    # ------------------------------------------------------------------
    def _emit(self, **kwargs):
        if self._progress:
            try:
                self._progress(kwargs)
            except Exception:
                pass

    def _time_exceeded(self) -> bool:
        return (time.time() - self._start_time) > self.max_time

    @staticmethod
    def _strip_code_block(text: str) -> str:
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        return text.strip()

    def _parse_json_array(self, text: str) -> List[str]:
        text = self._strip_code_block(text)
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [str(item) for item in parsed]
        except Exception:
            pass

        match = re.search(r"\[[\s\S]*\]", text)
        if match:
            try:
                parsed = json.loads(match.group())
                if isinstance(parsed, list):
                    return [str(item) for item in parsed]
            except Exception:
                pass

        # Harvest quoted strings
        items = re.findall(r'"([^"]{3,120})"', text)
        return items if items else []

    def _parse_json_object(self, text: str) -> Optional[Dict]:
        text = self._strip_code_block(text)
        try:
            return json.loads(text)
        except Exception:
            pass
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            try:
                return json.loads(match.group())
            except Exception:
                pass
        return None

    def _format_findings(self, findings: List[Dict]) -> str:
        parts = []
        for i, f in enumerate(findings, 1):
            url = f.get("url", "")
            title = f.get("title", "") or url
            summary = f.get("summary", "")
            key_facts = f.get("key_facts", [])
            facts_str = ("\n- " + "\n- ".join(key_facts)) if key_facts else ""
            parts.append(f"### Finding {i}: [{title}]({url})\n{summary}{facts_str}")
        return "\n\n".join(parts)

    def get_stats(self) -> Dict:
        elapsed = time.time() - self._start_time if self._start_time else 0
        stats = {
            "Duration": f"{elapsed:.1f}s",
            "Rounds": self.round_count,
            "Queries": len(self.queries_used),
            "URLs": len(self.urls_fetched),
            "Model": self.llm_model,
        }
        if self.providers_used:
            stats["Search"] = ", ".join(self.providers_used)
        if self.category:
            stats["Category"] = self.category.capitalize()
        return stats
