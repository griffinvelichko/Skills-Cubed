"""Recover partial eval results JSON from run_eval_slice console logs.

Parses lines like:
  Baseline [12]: score=4.0 ...
  Continual [27]: score=2.0 skill=none skills_total=16 ...

and writes eval_output/eval_results.partial.json so visualize_eval.py can
generate charts even if the run crashed before final export.
"""

import argparse
import json
import re
from pathlib import Path


BASELINE_RE = re.compile(r"Baseline \[(\d+)\]: score=([0-9]+(?:\.[0-9]+)?)")
CONTINUAL_RE = re.compile(
    r"Continual \[(\d+)\]: score=([0-9]+(?:\.[0-9]+)?) "
    r"skill=([^\s]+)\s+skills_total=(\d+)"
)


def main(log_path: Path, size: int):
    text = log_path.read_text(encoding="utf-8", errors="ignore")

    baseline_by_idx: dict[int, float] = {}
    continual_by_idx: dict[int, tuple[float, str, int]] = {}

    for line in text.splitlines():
        b = BASELINE_RE.search(line)
        if b:
            idx = int(b.group(1))
            score = float(b.group(2))
            baseline_by_idx[idx] = score
            continue

        c = CONTINUAL_RE.search(line)
        if c:
            idx = int(c.group(1))
            score = float(c.group(2))
            skill_id = c.group(3)
            skills_total = int(c.group(4))
            continual_by_idx[idx] = (score, skill_id, skills_total)

    baseline = [
        {
            "conversation_id": str(i),
            "judge_score": baseline_by_idx[i],
            "skill_used": False,
            "skill_id": None,
            "resolution_time_ms": 0.0,
        }
        for i in sorted(baseline_by_idx)
    ]

    continual = []
    max_skills_created = 0
    for i in sorted(continual_by_idx):
        score, skill_id, skills_total = continual_by_idx[i]
        max_skills_created = max(max_skills_created, skills_total)
        continual.append(
            {
                "conversation_id": str(i),
                "judge_score": score,
                "skill_used": skill_id != "none",
                "skill_id": None if skill_id == "none" else skill_id,
                "resolution_time_ms": 0.0,
            }
        )

    b_scores = [c["judge_score"] for c in baseline]
    c_scores = [c["judge_score"] for c in continual]
    b_avg = sum(b_scores) / len(b_scores) if b_scores else 0.0
    c_avg = sum(c_scores) / len(c_scores) if c_scores else 0.0

    payload = {
        "meta": {
            "size": size,
            "run_id": "recovered-from-log",
            "run_prefix": "recovered:",
        },
        "progress": {
            "baseline_last_index": max(baseline_by_idx.keys(), default=-1),
            "continual_last_index": max(continual_by_idx.keys(), default=-1),
        },
        "baseline": baseline,
        "continual": continual,
        "skills_created": max_skills_created,
        "summary": {
            "baseline_avg_score": b_avg,
            "continual_avg_score": c_avg,
            "improvement": c_avg - b_avg if b_scores and c_scores else 0.0,
            "baseline_count": len(baseline),
            "continual_count": len(continual),
        },
    }

    out_dir = Path(__file__).resolve().parent.parent / "eval_output"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / "eval_results.partial.json"
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"Recovered baseline rows:  {len(baseline)}")
    print(f"Recovered continual rows: {len(continual)}")
    print(f"Recovered skills_created: {max_skills_created}")
    print(f"Baseline avg:             {b_avg:.2f}")
    print(f"Continual avg:            {c_avg:.2f}")
    print(f"Improvement:              {c_avg - b_avg:+.2f}")
    print(f"Wrote: {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Recover eval partial JSON from console logs")
    parser.add_argument("--log", required=True, type=Path, help="Path to console log text file")
    parser.add_argument("--size", default=50, type=int, help="Configured run size (default: 50)")
    args = parser.parse_args()
    main(args.log, args.size)
