"""Run eval harness: baseline (no skills) vs continual learning on same conversations.

Usage:
    venv/bin/python3 scripts/run_eval_slice.py
    venv/bin/python3 scripts/run_eval_slice.py --size 25
"""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# Force all LLM calls to use Flash (including create/update orchestration)
os.environ["GEMINI_PRO_MODEL"] = os.environ.get("GEMINI_FLASH_MODEL", "gemini-3-flash-preview")

from src.eval.harness import EvaluationHarness, load_dataset

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "eval_output"

logger = logging.getLogger(__name__)


async def main(size: int, clear_legacy: bool):
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
    await harness.clear_eval_skills(clear_legacy=clear_legacy)

    # Phase 1: Baseline (no skills)
    logger.info("=== Phase 1: Baseline (%d conversations, no skills) ===", len(conversations))
    baseline = await harness.run_baseline(conversations)

    # Phase 2: Continual learning (same conversations, with skill search/create/update)
    logger.info("=== Phase 2: Continual Learning (%d conversations) ===", len(conversations))
    continual = await harness.run_continual(conversations)

    # Export
    output_path = str(OUTPUT_DIR / "eval_results.json")
    EvaluationHarness.export_results(baseline, continual, len(harness._eval_skill_ids), output_path)

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
    print(f"  Output: {output_path}")
    print(f"  Run: venv/bin/python3 scripts/visualize_eval.py")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run eval: baseline vs continual learning")
    parser.add_argument("--size", type=int, default=50, help="Number of conversations (default: 50)")
    parser.add_argument("--clear-legacy", action="store_true", help="Remove old un-prefixed eval skills")
    args = parser.parse_args()

    try:
        asyncio.run(main(args.size, args.clear_legacy))
    except KeyboardInterrupt:
        print("\nInterrupted", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"\nFAILED: {e}", file=sys.stderr)
        sys.exit(1)
