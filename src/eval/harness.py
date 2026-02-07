"""Evaluation harness — measures resolution quality improvement via continual learning.

Phases:
  1. Baseline — Flash resolves each conversation with NO skill access. LLM judge scores.
  2. Continual — Flash resolves with skill search. Creates/updates skills as it goes.
     Skills from conversation N are available for conversation N+1.

Same conversations run in both phases. The improvement curve shows judge scores
rising in continual as skills accumulate, vs flat baseline.
"""

import asyncio
import gzip
import inspect
import json
import logging
import os
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from pathlib import Path

from src.eval.metrics import ConversationMetrics, AggregateMetrics
from src.eval.resolution import determine_resolution

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "abcd" / "data"
ProgressHook = Callable[[str, int, list[ConversationMetrics]], Awaitable[None] | None]


# ---------------------------------------------------------------------------
# Data loading helpers
# ---------------------------------------------------------------------------

def load_dataset(split: str) -> list[dict]:
    """Load ABCD conversations by split name ('train', 'dev')."""
    gz_path = DATA_DIR / "abcd_v1.1.json.gz"
    json_path = DATA_DIR / "abcd_v1.1.json"

    if json_path.exists():
        with open(json_path) as f:
            data = json.load(f)
    elif gz_path.exists():
        with gzip.open(gz_path, "rt") as f:
            data = json.load(f)
    else:
        raise FileNotFoundError(f"No ABCD data found at {DATA_DIR}")

    if split not in data:
        raise ValueError(f"Split '{split}' not in dataset (available: {list(data.keys())})")
    return data[split]


def load_kb() -> dict:
    with open(DATA_DIR / "kb.json") as f:
        return json.load(f)


def extract_query(conversation: dict) -> str:
    """First 1-3 customer utterances before any action occurs."""
    lines = []
    for turn in conversation.get("original", []):
        speaker = turn[0]
        text = turn[1]
        if speaker == "action":
            break
        if speaker == "customer":
            lines.append(text)
            if len(lines) >= 3:
                break
    return " ".join(lines) if lines else ""


def extract_ground_truth(conversation: dict) -> str:
    """Extract agent turns + actions as the ground truth resolution."""
    lines = []
    for turn in conversation.get("original", []):
        speaker = turn[0]
        text = turn[1]
        if speaker == "agent":
            lines.append(f"Agent: {text}")
        elif speaker == "action":
            lines.append(f"[Action: {text}]")
    return "\n".join(lines)


def format_conversation(conversation: dict) -> str:
    """Format full conversation as readable text for create/update."""
    lines = []
    for turn in conversation.get("original", []):
        speaker = turn[0].capitalize()
        text = turn[1]
        lines.append(f"{speaker}: {text}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

RESOLVE_PROMPT = """\
You are a customer service agent. A customer has the following issue:

{query}
{skill_section}
Provide a clear, specific resolution to the customer's issue. Include concrete steps the customer or agent should take. Be concise but thorough."""

RESOLVE_SKILL_SECTION = """
You have this resolution playbook to guide your response:
{skill_context}
"""

JUDGE_PROMPT = """\
You are evaluating an AI customer service agent's response quality.

CUSTOMER ISSUE:
{query}

GROUND TRUTH RESOLUTION (from expert human agent):
{ground_truth}

AI AGENT'S PROPOSED RESOLUTION:
{resolution}

Rate the AI's resolution on a scale of 1-5:
1 = Completely wrong, irrelevant, or harmful advice
2 = Addresses the topic but misses key steps or gives incorrect info
3 = Partially correct, covers some important steps but incomplete
4 = Good resolution, covers most important aspects correctly
5 = Excellent, matches or exceeds ground truth quality

Return ONLY valid JSON: {{"score": N, "reasoning": "brief explanation"}}"""


# ---------------------------------------------------------------------------
# Retry helper for transient API errors (503, rate limits)
# ---------------------------------------------------------------------------

MAX_RETRIES = 4
BACKOFF_BASE = 2.0

async def _retry(coro_fn, *args, label: str = ""):
    for attempt in range(MAX_RETRIES + 1):
        try:
            return await coro_fn(*args)
        except Exception as e:
            err_str = str(e)
            transient = "503" in err_str or "overloaded" in err_str.lower() or "unavailable" in err_str.lower()
            if not transient or attempt == MAX_RETRIES:
                raise
            wait = BACKOFF_BASE * (2 ** attempt)
            logger.warning("Transient error (%s), retry %d/%d in %.0fs: %s", label, attempt + 1, MAX_RETRIES, wait, err_str[:120])
            await asyncio.sleep(wait)


# ---------------------------------------------------------------------------
# Resolution generation & judging
# ---------------------------------------------------------------------------

async def generate_resolution(query: str, skill_context: str | None = None) -> str:
    from src.llm.client import call_flash

    if skill_context:
        skill_section = RESOLVE_SKILL_SECTION.format(skill_context=skill_context)
    else:
        skill_section = ""

    prompt = RESOLVE_PROMPT.format(query=query, skill_section=skill_section)
    return await call_flash(prompt)


async def judge_resolution(query: str, resolution: str, ground_truth: str) -> float:
    from src.llm.client import call_flash

    prompt = JUDGE_PROMPT.format(query=query, resolution=resolution, ground_truth=ground_truth)
    response = await call_flash(prompt)

    # Parse score from JSON response
    try:
        cleaned = re.sub(r"^```(?:json)?\s*", "", response.strip())
        cleaned = re.sub(r"\s*```$", "", cleaned)
        result = json.loads(cleaned)
        score = float(result["score"])
        return max(1.0, min(5.0, score))  # clamp to [1, 5]
    except (json.JSONDecodeError, KeyError, ValueError, TypeError):
        logger.warning("Judge returned unparseable response, defaulting to 3.0: %s", response[:100])
        return 3.0


async def _increment_times_used(skill_id: str):
    from src.db.connection import get_driver

    driver = await get_driver()
    async with driver.session() as session:
        result = await session.run(
            "MATCH (s:Skill {skill_id: $sid}) SET s.times_used = coalesce(s.times_used, 0) + 1",
            sid=skill_id,
        )
        await result.consume()


async def _call_progress_hook(
    progress_hook: ProgressHook | None,
    phase: str,
    index: int,
    results: list[ConversationMetrics],
):
    if progress_hook is None:
        return
    maybe_awaitable = progress_hook(phase, index, results)
    if inspect.isawaitable(maybe_awaitable):
        await maybe_awaitable


# ---------------------------------------------------------------------------
# Evaluation Harness
# ---------------------------------------------------------------------------

class EvaluationHarness:
    def __init__(self):
        self.kb = load_kb()
        self._eval_skill_ids: set[str] = set()
        self._run_prefix = os.getenv("EVAL_RUN_PREFIX", "torrin:")
        self._run_id = f"{self._run_prefix}{str(uuid.uuid4())[:8]}"

    async def setup(self):
        from src.db import ensure_indexes
        await ensure_indexes()

    async def clear_eval_skills(self, clear_legacy: bool = False):
        from src.db.connection import get_driver

        driver = await get_driver()
        async with driver.session() as session:
            result = await session.run(
                "MATCH (s:Skill) WHERE s.eval_run STARTS WITH $prefix DETACH DELETE s",
                prefix=self._run_prefix,
            )
            summary = await result.consume()
            deleted = summary.counters.nodes_deleted
            logger.info("Cleared %d eval-tagged skill nodes (prefix=%s)", deleted, self._run_prefix)

            if clear_legacy:
                result = await session.run(
                    "MATCH (s:Skill) WHERE s.eval_run IS NOT NULL "
                    "AND NOT s.eval_run CONTAINS ':' DETACH DELETE s"
                )
                legacy_summary = await result.consume()
                logger.info("Cleared %d legacy eval skill nodes", legacy_summary.counters.nodes_deleted)

        self._eval_skill_ids.clear()

    async def _tag_eval_skill(self, skill_id: str):
        from src.db.connection import get_driver

        driver = await get_driver()
        async with driver.session() as session:
            result = await session.run(
                "MATCH (s:Skill {skill_id: $sid}) SET s.eval_run = $run_id",
                sid=skill_id, run_id=self._run_id,
            )
            await result.consume()

    async def load_eval_skill_ids(self) -> set[str]:
        """Reload eval-owned skill IDs for the current run_id from DB."""
        from src.db.connection import get_driver

        driver = await get_driver()
        async with driver.session() as session:
            result = await session.run(
                "MATCH (s:Skill) WHERE s.eval_run = $run_id RETURN s.skill_id AS skill_id",
                run_id=self._run_id,
            )
            rows = await result.values("skill_id")
        self._eval_skill_ids = set(rows)
        logger.info("Loaded %d eval skills for run_id=%s", len(self._eval_skill_ids), self._run_id)
        return self._eval_skill_ids

    async def run_baseline(
        self,
        conversations: list[dict],
        start_index: int = 0,
        prior_results: list[ConversationMetrics] | None = None,
        progress_hook: ProgressHook | None = None,
    ) -> list[ConversationMetrics]:
        """Baseline: Flash resolves each conversation with NO skill access.

        Establishes the quality floor — what Flash can do on its own.
        """
        results = list(prior_results or [])
        skipped = 0

        for i in range(start_index, len(conversations)):
            conv = conversations[i]
            try:
                resolved = determine_resolution(conv, self.kb)
                if resolved is None:
                    skipped += 1
                    continue

                query = extract_query(conv)
                if not query:
                    skipped += 1
                    continue

                ground_truth = extract_ground_truth(conv)

                start = time.monotonic()
                resolution = await _retry(generate_resolution, query, None, label=f"baseline-resolve:{i}")
                score = await _retry(judge_resolution, query, resolution, ground_truth, label=f"baseline-judge:{i}")
                elapsed = (time.monotonic() - start) * 1000

                conv_id = str(conv.get("convo_id", i))
                results.append(ConversationMetrics(
                    conversation_id=conv_id,
                    judge_score=score,
                    skill_used=False,
                    resolution_time_ms=elapsed,
                ))

                logger.info("Baseline [%d]: score=%.1f time=%.0fms", i, score, elapsed)

            except Exception:
                logger.exception("Baseline error on conversation %d", i)
                continue
            finally:
                await _call_progress_hook(progress_hook, "baseline", i, results)

        logger.info("Baseline complete: %d scored, %d skipped, avg=%.2f",
                     len(results), skipped,
                     sum(r.judge_score for r in results) / len(results) if results else 0)
        return results

    async def run_continual(
        self,
        conversations: list[dict],
        start_index: int = 0,
        prior_results: list[ConversationMetrics] | None = None,
        progress_hook: ProgressHook | None = None,
    ) -> list[ConversationMetrics]:
        """Continual learning: search → resolve → judge → create/update.

        Skills from conversation N are immediately available for N+1.
        """
        from src.orchestration.create import create_skill_orchestration
        from src.orchestration.search import search_skills_orchestration
        from src.orchestration.update import update_skill_orchestration

        results = list(prior_results or [])
        skipped = 0

        for i in range(start_index, len(conversations)):
            conv = conversations[i]
            try:
                resolved = determine_resolution(conv, self.kb)
                if resolved is None:
                    skipped += 1
                    continue

                query = extract_query(conv)
                if not query:
                    skipped += 1
                    continue

                ground_truth = extract_ground_truth(conv)

                # Search for existing skills
                start = time.monotonic()
                search_result = await _retry(search_skills_orchestration, query, label=f"continual-search:{i}")
                skill_hit = search_result.skill is not None

                # Generate resolution — with or without skill context
                skill_context = None
                skill_id = None
                if skill_hit:
                    skill_context = search_result.skill.resolution_md
                    skill_id = search_result.skill.skill_id
                    await _increment_times_used(skill_id)

                resolution = await _retry(generate_resolution, query, skill_context, label=f"continual-resolve:{i}")

                # Judge the resolution
                score = await _retry(judge_resolution, query, resolution, ground_truth, label=f"continual-judge:{i}")
                elapsed = (time.monotonic() - start) * 1000

                # Learn: create or update skill from this conversation
                if resolved and not skill_hit:
                    formatted = format_conversation(conv)
                    try:
                        create_result = await _retry(create_skill_orchestration, formatted, label=f"create:{i}")
                        if create_result.created:
                            self._eval_skill_ids.add(create_result.skill_id)
                            await self._tag_eval_skill(create_result.skill_id)
                    except Exception:
                        logger.exception("Create failed on conversation %d", i)

                elif resolved and skill_hit:
                    formatted = format_conversation(conv)
                    try:
                        await _retry(update_skill_orchestration, skill_id, formatted, label=f"update:{i}")
                    except Exception:
                        logger.exception("Update failed on conversation %d", i)

                conv_id = str(conv.get("convo_id", i))
                results.append(ConversationMetrics(
                    conversation_id=conv_id,
                    judge_score=score,
                    skill_used=skill_hit,
                    skill_id=skill_id,
                    resolution_time_ms=elapsed,
                ))

                logger.info("Continual [%d]: score=%.1f skill=%s skills_total=%d time=%.0fms",
                            i, score, skill_id or "none", len(self._eval_skill_ids), elapsed)

            except Exception:
                logger.exception("Continual error on conversation %d", i)
                continue
            finally:
                await _call_progress_hook(progress_hook, "continual", i, results)

        logger.info(
            "Continual complete: %d scored, %d skipped, %d skills created, avg=%.2f",
            len(results), skipped, len(self._eval_skill_ids),
            sum(r.judge_score for r in results) / len(results) if results else 0,
        )
        return results

    @staticmethod
    def export_results(baseline: list[ConversationMetrics],
                       continual: list[ConversationMetrics],
                       skills_created: int,
                       output_path: str):
        b_scores = [r.judge_score for r in baseline]
        c_scores = [r.judge_score for r in continual]

        data = {
            "baseline": [asdict(m) for m in baseline],
            "continual": [asdict(m) for m in continual],
            "skills_created": skills_created,
            "summary": {
                "baseline_avg_score": sum(b_scores) / len(b_scores) if b_scores else 0,
                "continual_avg_score": sum(c_scores) / len(c_scores) if c_scores else 0,
                "improvement": (sum(c_scores) / len(c_scores) - sum(b_scores) / len(b_scores)) if b_scores and c_scores else 0,
                "baseline_count": len(baseline),
                "continual_count": len(continual),
            },
        }
        with open(output_path, "w") as f:
            json.dump(data, f, indent=2)
