"""Run eval harness: baseline (no skills) vs continual learning on same conversations.

Usage:
    venv/bin/python3 scripts/run_eval_slice.py
    venv/bin/python3 scripts/run_eval_slice.py --size 25
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from dataclasses import asdict
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# Force all LLM calls to use Flash (including create/update orchestration)
os.environ["GEMINI_PRO_MODEL"] = os.environ.get("GEMINI_FLASH_MODEL", "gemini-3-flash-preview")

from src.eval.harness import EvaluationHarness, load_dataset
from src.eval.metrics import ConversationMetrics

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "eval_output"
CHECKPOINT_PATH = OUTPUT_DIR / "eval_results.partial.json"
FINAL_PATH = OUTPUT_DIR / "eval_results.json"

logger = logging.getLogger(__name__)


def _build_payload(
    baseline: list[ConversationMetrics],
    continual: list[ConversationMetrics],
    skills_created: int,
    run_id: str,
    run_prefix: str,
    size: int,
    baseline_last_index: int,
    continual_last_index: int,
) -> dict:
    b_scores = [r.judge_score for r in baseline]
    c_scores = [r.judge_score for r in continual]
    return {
        "meta": {
            "size": size,
            "run_id": run_id,
            "run_prefix": run_prefix,
        },
        "progress": {
            "baseline_last_index": baseline_last_index,
            "continual_last_index": continual_last_index,
        },
        "baseline": [asdict(m) for m in baseline],
        "continual": [asdict(m) for m in continual],
        "skills_created": skills_created,
        "summary": {
            "baseline_avg_score": sum(b_scores) / len(b_scores) if b_scores else 0.0,
            "continual_avg_score": sum(c_scores) / len(c_scores) if c_scores else 0.0,
            "improvement": (sum(c_scores) / len(c_scores) - sum(b_scores) / len(b_scores)) if b_scores and c_scores else 0.0,
            "baseline_count": len(baseline),
            "continual_count": len(continual),
        },
    }


def _write_payload(path: Path, payload: dict):
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)


def _load_checkpoint(size: int) -> dict:
    with open(CHECKPOINT_PATH) as f:
        data = json.load(f)
    cp_size = data.get("meta", {}).get("size")
    if cp_size is not None and cp_size != size:
        raise ValueError(
            f"Checkpoint size mismatch: checkpoint has {cp_size}, requested {size}. "
            "Use matching --size, or delete eval_output/eval_results.partial.json."
        )
    return data


async def main(size: int, clear_legacy: bool, resume: bool):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    OUTPUT_DIR.mkdir(exist_ok=True)

    logger.info("Loading dataset...")
    conversations = load_dataset("train")[:size]
    logger.info("Using %d conversations for both baseline and continual", len(conversations))

    harness = EvaluationHarness()
    await harness.setup()

    baseline: list[ConversationMetrics] = []
    continual: list[ConversationMetrics] = []
    baseline_last_index = -1
    continual_last_index = -1

    if resume:
        if not CHECKPOINT_PATH.exists():
            raise FileNotFoundError(
                f"--resume specified but checkpoint not found: {CHECKPOINT_PATH}"
            )
        checkpoint = _load_checkpoint(size)
        meta = checkpoint.get("meta", {})
        progress = checkpoint.get("progress", {})

        harness._run_prefix = meta.get("run_prefix", harness._run_prefix)
        harness._run_id = meta.get("run_id", harness._run_id)
        await harness.load_eval_skill_ids()

        baseline = [ConversationMetrics(**m) for m in checkpoint.get("baseline", [])]
        continual = [ConversationMetrics(**m) for m in checkpoint.get("continual", [])]
        baseline_last_index = int(progress.get("baseline_last_index", -1))
        continual_last_index = int(progress.get("continual_last_index", -1))

        logger.info(
            "Resuming run_id=%s (baseline idx=%d, continual idx=%d, skills=%d)",
            harness._run_id,
            baseline_last_index,
            continual_last_index,
            len(harness._eval_skill_ids),
        )
    else:
        if CHECKPOINT_PATH.exists():
            CHECKPOINT_PATH.unlink()
        await harness.clear_eval_skills(clear_legacy=clear_legacy)

    async def _progress_hook(phase: str, index: int, results: list[ConversationMetrics]):
        nonlocal baseline, continual, baseline_last_index, continual_last_index
        if phase == "baseline":
            baseline = results
            baseline_last_index = index
        else:
            continual = results
            continual_last_index = index
        payload = _build_payload(
            baseline=baseline,
            continual=continual,
            skills_created=len(harness._eval_skill_ids),
            run_id=harness._run_id,
            run_prefix=harness._run_prefix,
            size=size,
            baseline_last_index=baseline_last_index,
            continual_last_index=continual_last_index,
        )
        _write_payload(CHECKPOINT_PATH, payload)

    # Phase 1: Baseline (no skills)
    if baseline_last_index < len(conversations) - 1:
        logger.info(
            "=== Phase 1: Baseline (%d conversations, no skills) [start=%d] ===",
            len(conversations),
            baseline_last_index + 1,
        )
        baseline = await harness.run_baseline(
            conversations,
            start_index=baseline_last_index + 1,
            prior_results=baseline,
            progress_hook=_progress_hook,
        )
    else:
        logger.info("=== Phase 1: Baseline already complete (%d/%d) ===", len(baseline), len(conversations))

    # Phase 2: Continual learning (same conversations, with skill search/create/update)
    if continual_last_index < len(conversations) - 1:
        logger.info(
            "=== Phase 2: Continual Learning (%d conversations) [start=%d] ===",
            len(conversations),
            continual_last_index + 1,
        )
        continual = await harness.run_continual(
            conversations,
            start_index=continual_last_index + 1,
            prior_results=continual,
            progress_hook=_progress_hook,
        )
    else:
        logger.info("=== Phase 2: Continual already complete (%d/%d) ===", len(continual), len(conversations))

    # Export final + keep checkpoint as recovery artifact
    payload = _build_payload(
        baseline=baseline,
        continual=continual,
        skills_created=len(harness._eval_skill_ids),
        run_id=harness._run_id,
        run_prefix=harness._run_prefix,
        size=size,
        baseline_last_index=len(conversations) - 1,
        continual_last_index=len(conversations) - 1,
    )
    _write_payload(FINAL_PATH, payload)
    _write_payload(CHECKPOINT_PATH, payload)

    # Summary
    b_avg = sum(r.judge_score for r in baseline) / len(baseline) if baseline else 0
    c_avg = sum(r.judge_score for r in continual) / len(continual) if continual else 0
    c_skill_used = sum(1 for r in continual if r.skill_used)

    print("\n" + "=" * 60)
    print("EVAL RESULTS")
    print("=" * 60)
    print(f"  Conversations:       {len(conversations)}")
    print(f"  Baseline scored:     {len(baseline)}")
    print(f"  Continual scored:    {len(continual)}")
    print(f"  Skills created:      {len(harness._eval_skill_ids)}")
    print(f"  Skills used:         {c_skill_used}/{len(continual)}")
    print(f"  Baseline avg score:  {b_avg:.2f}/5")
    print(f"  Continual avg score: {c_avg:.2f}/5")
    print(f"  Improvement:         {c_avg - b_avg:+.2f}")
    print("=" * 60)
    print(f"  Output: {FINAL_PATH}")
    print(f"  Checkpoint: {CHECKPOINT_PATH}")
    print(f"  Run: venv/bin/python3 scripts/visualize_eval.py")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run eval: baseline vs continual learning")
    parser.add_argument("--size", type=int, default=50, help="Number of conversations (default: 50)")
    parser.add_argument("--clear-legacy", action="store_true", help="Remove old un-prefixed eval skills")
    parser.add_argument("--resume", action="store_true", help="Resume from eval_output/eval_results.partial.json")
    args = parser.parse_args()

    try:
        asyncio.run(main(args.size, args.clear_legacy, args.resume))
    except KeyboardInterrupt:
        print("\nInterrupted", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"\nFAILED: {e}", file=sys.stderr)
        sys.exit(1)
