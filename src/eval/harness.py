"""Evaluation harness — 3-phase benchmark over ABCD conversations.

Phases:
  1. Baseline — search-only pass (no eval skills exist yet → hit rate is 0%)
  2. Learning — sequential pass creating/updating skills from train split
  3. Post-learning — re-run dev split to measure improvement over baseline

Each phase outputs dual MetricsTracker views (eval_scoped + global).
"""

import asyncio
import gzip
import json
import logging
import time
import uuid
from dataclasses import asdict
from pathlib import Path

from src.eval.metrics import ConversationMetrics, MetricsTracker
from src.eval.resolution import determine_resolution

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "abcd" / "data"


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
    """Load kb.json ground truth (subflow -> expected action sequence)."""
    with open(DATA_DIR / "kb.json") as f:
        return json.load(f)


def extract_query(conversation: dict) -> str:
    """First 1-3 customer utterances before any action occurs.

    Simulates what a real customer would type as their initial query.
    """
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


def format_conversation(conversation: dict) -> str:
    """Format full conversation as readable text for create/update."""
    lines = []
    for turn in conversation.get("original", []):
        speaker = turn[0].capitalize()
        text = turn[1]
        lines.append(f"{speaker}: {text}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Evaluation Harness
# ---------------------------------------------------------------------------

class EvaluationHarness:
    def __init__(self):
        self.kb = load_kb()
        self._eval_owned_ids: set[str] = set()
        self._run_id = str(uuid.uuid4())[:8]

    async def setup(self):
        """Call before first phase: ensure indexes exist."""
        from src.db import ensure_indexes
        await ensure_indexes()

    async def clear_eval_skills(self):
        """Delete only eval-owned Skill nodes. Leaves teammate/demo data intact."""
        from src.db.connection import get_driver

        driver = await get_driver()
        async with driver.session() as session:
            result = await session.run(
                "MATCH (s:Skill) WHERE s.eval_run IS NOT NULL DETACH DELETE s"
            )
            summary = await result.consume()
            deleted = summary.counters.nodes_deleted
            logger.info("Cleared %d eval-tagged skill nodes", deleted)
        self._eval_owned_ids.clear()

    async def _tag_eval_skill(self, skill_id: str):
        """Tag a newly-created skill with the current eval run ID."""
        from src.db.connection import get_driver

        driver = await get_driver()
        async with driver.session() as session:
            result = await session.run(
                "MATCH (s:Skill {skill_id: $sid}) SET s.eval_run = $run_id",
                sid=skill_id,
                run_id=self._run_id,
            )
            await result.consume()

    async def run_baseline(self, conversations: list[dict]) -> dict[str, MetricsTracker]:
        """Phase 1: search pass with eval-scope filtering.

        No eval skills exist yet, so eval-scoped hit rate is genuinely 0%.
        Global tracker still records any pre-existing skill hits.
        """
        from src.orchestration.search import search_skills_orchestration

        eval_tracker = MetricsTracker()
        global_tracker = MetricsTracker()
        skipped = 0

        for i, conv in enumerate(conversations):
            try:
                resolved = determine_resolution(conv, self.kb)
                if resolved is None:
                    skipped += 1
                    continue

                query = extract_query(conv)
                if not query:
                    skipped += 1
                    continue

                start = time.monotonic()
                result = await search_skills_orchestration(query)
                elapsed = (time.monotonic() - start) * 1000

                raw_hit = result.skill is not None
                eval_hit = raw_hit and result.skill.skill_id in self._eval_owned_ids

                conv_id = str(conv.get("convo_id", i))

                eval_tracker.record(ConversationMetrics(
                    conversation_id=conv_id,
                    resolved=resolved,
                    model_used="flash" if eval_hit else "pro",
                    skill_found=eval_hit,
                    used_pro_fallback=not eval_hit,
                    resolution_time_ms=elapsed,
                ))

                global_tracker.record(ConversationMetrics(
                    conversation_id=conv_id,
                    resolved=resolved,
                    model_used="flash" if raw_hit else "pro",
                    skill_found=raw_hit,
                    used_pro_fallback=not raw_hit,
                    resolution_time_ms=elapsed,
                ))

            except Exception:
                logger.exception("Baseline error on conversation %d", i)
                continue

        logger.info("Baseline complete: %d processed, %d skipped", len(eval_tracker._metrics), skipped)
        return {"eval_scoped": eval_tracker, "global": global_tracker}

    async def run_learning(
        self,
        conversations: list[dict],
        checkpoint_interval: int = 100,
    ) -> dict[str, MetricsTracker]:
        """Phase 2: sequential pass with skill creation and updates.

        Tracks eval_owned_ids to isolate from teammate/demo data.
        """
        from src.orchestration.create import create_skill_orchestration
        from src.orchestration.search import search_skills_orchestration
        from src.orchestration.update import update_skill_orchestration

        eval_tracker = MetricsTracker()
        global_tracker = MetricsTracker()
        skipped = 0

        for i, conv in enumerate(conversations):
            try:
                resolved = determine_resolution(conv, self.kb)
                if resolved is None:
                    skipped += 1
                    continue

                query = extract_query(conv)
                if not query:
                    skipped += 1
                    continue

                start = time.monotonic()
                result = await search_skills_orchestration(query)
                elapsed = (time.monotonic() - start) * 1000

                raw_hit = result.skill is not None
                eval_hit = raw_hit and result.skill.skill_id in self._eval_owned_ids

                # Create/update control flow
                if resolved and not raw_hit:
                    # No skill at all — create new
                    formatted = format_conversation(conv)
                    try:
                        create_result = await create_skill_orchestration(formatted)
                        if create_result.created:
                            self._eval_owned_ids.add(create_result.skill_id)
                            await self._tag_eval_skill(create_result.skill_id)
                    except Exception:
                        logger.exception("Create failed on conversation %d", i)

                elif resolved and eval_hit:
                    # Eval-owned skill found — update it
                    formatted = format_conversation(conv)
                    try:
                        await update_skill_orchestration(result.skill.skill_id, formatted)
                    except Exception:
                        logger.exception("Update failed on conversation %d", i)

                # resolved AND raw_hit AND NOT eval_hit → non-eval skill, read-only

                conv_id = str(conv.get("convo_id", i))

                eval_tracker.record(ConversationMetrics(
                    conversation_id=conv_id,
                    resolved=resolved,
                    model_used="flash" if eval_hit else "pro",
                    skill_found=eval_hit,
                    used_pro_fallback=not eval_hit,
                    resolution_time_ms=elapsed,
                ))

                global_tracker.record(ConversationMetrics(
                    conversation_id=conv_id,
                    resolved=resolved,
                    model_used="flash" if raw_hit else "pro",
                    skill_found=raw_hit,
                    used_pro_fallback=not raw_hit,
                    resolution_time_ms=elapsed,
                ))

                # Periodic checkpoint
                processed = len(eval_tracker._metrics)
                if checkpoint_interval and processed % checkpoint_interval == 0:
                    label = f"learning_{processed}"
                    eval_tracker.checkpoint(label)
                    global_tracker.checkpoint(label)
                    logger.info("Checkpoint at %d conversations", processed)

            except Exception:
                logger.exception("Learning error on conversation %d", i)
                continue

        logger.info(
            "Learning complete: %d processed, %d skipped, %d eval skills created",
            len(eval_tracker._metrics), skipped, len(self._eval_owned_ids),
        )
        return {"eval_scoped": eval_tracker, "global": global_tracker}

    async def run_post_learning(self, conversations: list[dict]) -> dict[str, MetricsTracker]:
        """Phase 3: re-run dev split to show improvement over baseline.

        Same eval-scope filtering as baseline — only eval-owned skill hits count.
        """
        from src.orchestration.search import search_skills_orchestration

        eval_tracker = MetricsTracker()
        global_tracker = MetricsTracker()
        skipped = 0

        for i, conv in enumerate(conversations):
            try:
                resolved = determine_resolution(conv, self.kb)
                if resolved is None:
                    skipped += 1
                    continue

                query = extract_query(conv)
                if not query:
                    skipped += 1
                    continue

                start = time.monotonic()
                result = await search_skills_orchestration(query)
                elapsed = (time.monotonic() - start) * 1000

                raw_hit = result.skill is not None
                eval_hit = raw_hit and result.skill.skill_id in self._eval_owned_ids

                conv_id = str(conv.get("convo_id", i))

                eval_tracker.record(ConversationMetrics(
                    conversation_id=conv_id,
                    resolved=resolved,
                    model_used="flash" if eval_hit else "pro",
                    skill_found=eval_hit,
                    used_pro_fallback=not eval_hit,
                    resolution_time_ms=elapsed,
                ))

                global_tracker.record(ConversationMetrics(
                    conversation_id=conv_id,
                    resolved=resolved,
                    model_used="flash" if raw_hit else "pro",
                    skill_found=raw_hit,
                    used_pro_fallback=not raw_hit,
                    resolution_time_ms=elapsed,
                ))

            except Exception:
                logger.exception("Post-learning error on conversation %d", i)
                continue

        logger.info("Post-learning complete: %d processed, %d skipped", len(eval_tracker._metrics), skipped)
        return {"eval_scoped": eval_tracker, "global": global_tracker}

    @staticmethod
    def export_dual(trackers: dict[str, MetricsTracker], output_path: str):
        """Export dual-view metrics to a single JSON file."""
        data = {}
        for scope, tracker in trackers.items():
            data[scope] = {
                "conversations": [asdict(m) for m in tracker._metrics],
                "checkpoints": tracker._checkpoints,
                "final": asdict(tracker.aggregate()),
            }
        with open(output_path, "w") as f:
            json.dump(data, f, indent=2)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

async def _main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    logger.info("Loading datasets...")
    dev = load_dataset("dev")
    train = load_dataset("train")
    logger.info("Loaded %d dev, %d train conversations", len(dev), len(train))

    harness = EvaluationHarness()
    await harness.setup()
    await harness.clear_eval_skills()

    logger.info("=== Phase 1: Baseline ===")
    baseline = await harness.run_baseline(dev)
    EvaluationHarness.export_dual(baseline, "eval_baseline.json")

    logger.info("=== Phase 2: Learning ===")
    learning = await harness.run_learning(train)
    EvaluationHarness.export_dual(learning, "eval_learning.json")

    logger.info("=== Phase 3: Post-Learning ===")
    post = await harness.run_post_learning(dev)
    EvaluationHarness.export_dual(post, "eval_post_learning.json")

    # Summary
    b_eval = baseline["eval_scoped"].aggregate()
    p_eval = post["eval_scoped"].aggregate()
    logger.info("--- Eval-Scoped Results ---")
    logger.info("Baseline hit rate: %.1f%%", b_eval.judge_hit_rate * 100)
    logger.info("Post-learning hit rate: %.1f%%", p_eval.judge_hit_rate * 100)
    logger.info("Improvement: +%.1f pp", (p_eval.judge_hit_rate - b_eval.judge_hit_rate) * 100)
    logger.info("Skills created: %d", len(harness._eval_owned_ids))


if __name__ == "__main__":
    asyncio.run(_main())
