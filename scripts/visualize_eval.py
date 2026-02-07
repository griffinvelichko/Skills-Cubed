"""Generate visualization charts from eval results.

Reads eval_output/eval_results.json and produces:
  1. Resolution quality curve (running avg judge scores: baseline vs continual)
  2. Skill accumulation over conversations

Usage:
    venv/bin/python3 scripts/visualize_eval.py
"""

import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "eval_output"


def load_results() -> tuple[dict, Path]:
    final_path = OUTPUT_DIR / "eval_results.json"
    partial_path = OUTPUT_DIR / "eval_results.partial.json"
    if final_path.exists():
        path = final_path
    elif partial_path.exists():
        path = partial_path
        print(f"Using partial results: {partial_path}")
    else:
        print(f"Missing {final_path} (and no {partial_path}) — run scripts/run_eval_slice.py first", file=sys.stderr)
        sys.exit(1)
    with open(path) as f:
        return json.load(f), path


def compute_summary(data: dict) -> dict:
    baseline_scores = [c["judge_score"] for c in data.get("baseline", [])]
    continual_scores = [c["judge_score"] for c in data.get("continual", [])]
    b_avg = sum(baseline_scores) / len(baseline_scores) if baseline_scores else 0.0
    c_avg = sum(continual_scores) / len(continual_scores) if continual_scores else 0.0
    return {
        "baseline_count": len(baseline_scores),
        "continual_count": len(continual_scores),
        "baseline_avg_score": b_avg,
        "continual_avg_score": c_avg,
        "improvement": c_avg - b_avg if baseline_scores and continual_scores else 0.0,
    }


def running_average(scores: list[float]) -> list[float]:
    """Compute cumulative running average."""
    if not scores:
        return []
    cumsum = np.cumsum(scores)
    return (cumsum / np.arange(1, len(scores) + 1)).tolist()


def chart_quality_curve(data: dict):
    """Chart 1: Running average judge scores — baseline vs continual."""
    baseline_scores = [c["judge_score"] for c in data["baseline"]]
    continual_scores = [c["judge_score"] for c in data["continual"]]

    if not baseline_scores or not continual_scores:
        print("  Skipping quality curve — insufficient data")
        return

    b_running = running_average(baseline_scores)
    c_running = running_average(continual_scores)

    fig, ax = plt.subplots(figsize=(12, 6))

    xs_b = range(1, len(b_running) + 1)
    xs_c = range(1, len(c_running) + 1)

    ax.plot(xs_b, b_running, color="#e74c3c", linewidth=2, label="Baseline (no skills)", alpha=0.85)
    ax.plot(xs_c, c_running, color="#2ecc71", linewidth=2, label="Continual Learning", alpha=0.85)

    # Scatter individual scores with low alpha for context
    ax.scatter(xs_b, baseline_scores, color="#e74c3c", alpha=0.15, s=20, zorder=1)
    ax.scatter(xs_c, continual_scores, color="#2ecc71", alpha=0.15, s=20, zorder=1)

    # Mark conversations where a skill was used
    skill_xs = [i + 1 for i, c in enumerate(data["continual"]) if c["skill_used"]]
    skill_ys = [data["continual"][i]["judge_score"] for i in range(len(data["continual"])) if data["continual"][i]["skill_used"]]
    if skill_xs:
        ax.scatter(skill_xs, skill_ys, color="#3498db", marker="^", s=50, zorder=3,
                   label="Skill used", alpha=0.7)

    ax.set_xlabel("Conversation #", fontsize=12)
    ax.set_ylabel("Judge Score (1-5)", fontsize=12)
    ax.set_title("Resolution Quality: Baseline vs Continual Learning", fontsize=14)
    ax.legend(fontsize=11)
    ax.grid(True, alpha=0.3)
    ax.set_ylim(0.5, 5.5)

    # Annotate final averages
    b_final = b_running[-1]
    c_final = c_running[-1]
    ax.annotate(f"Baseline: {b_final:.2f}", xy=(len(b_running), b_final),
                xytext=(10, -5), textcoords="offset points", fontsize=10, color="#e74c3c")
    ax.annotate(f"Continual: {c_final:.2f}", xy=(len(c_running), c_final),
                xytext=(10, 5), textcoords="offset points", fontsize=10, color="#2ecc71")

    fig.tight_layout()
    out = OUTPUT_DIR / "quality_curve.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"  Saved: {out}")


def chart_skill_growth(data: dict):
    """Chart 2: Cumulative skills created + skill use rate over conversations."""
    continual = data["continual"]
    if not continual:
        print("  Skipping skill growth — no continual data")
        return

    # Track cumulative skill creates (skill_used=False implies a create attempt happened)
    # We use the fact that skill_id is None when no skill was used (and a create may have happened)
    # Better: count unique skill_ids that appear for the first time
    seen_skills = set()
    cumulative = []
    skill_use_cumulative = []
    uses_so_far = 0

    for i, c in enumerate(continual):
        if c["skill_used"] and c["skill_id"]:
            uses_so_far += 1
            if c["skill_id"] not in seen_skills:
                seen_skills.add(c["skill_id"])
        cumulative.append(data["skills_created"])  # placeholder — we don't track per-conv

    # Better approach: infer from the data — skills_created is the total
    # We can approximate growth by counting conversations where skill_used=False
    # (those are create opportunities)
    creates = 0
    create_curve = []
    use_curve = []
    uses = 0
    for c in continual:
        if not c["skill_used"]:
            creates += 1  # approximate: not all result in actual creates (dups)
        else:
            uses += 1
        create_curve.append(creates)
        use_curve.append(uses)

    xs = range(1, len(continual) + 1)

    fig, ax1 = plt.subplots(figsize=(12, 6))

    ax1.plot(xs, create_curve, color="#e67e22", linewidth=2, label="Cumulative Create Attempts")
    ax1.fill_between(xs, create_curve, alpha=0.1, color="#e67e22")
    ax1.set_xlabel("Conversation #", fontsize=12)
    ax1.set_ylabel("Create Attempts", fontsize=12, color="#e67e22")

    ax2 = ax1.twinx()
    ax2.plot(xs, use_curve, color="#3498db", linewidth=2, linestyle="--", label="Cumulative Skill Uses")
    ax2.set_ylabel("Skill Uses", fontsize=12, color="#3498db")

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, fontsize=11, loc="upper left")

    ax1.set_title("Skill Growth: Creates and Uses Over Time", fontsize=14)
    ax1.grid(True, alpha=0.3)

    # Annotate totals
    ax1.annotate(f"Total: {data['skills_created']} skills created",
                 xy=(0.98, 0.02), xycoords="axes fraction", ha="right", fontsize=10,
                 color="#e67e22")

    fig.tight_layout()
    out = OUTPUT_DIR / "skill_growth.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"  Saved: {out}")


def chart_score_distribution(data: dict):
    """Chart 3: Score distribution histogram — baseline vs continual."""
    baseline_scores = [c["judge_score"] for c in data["baseline"]]
    continual_scores = [c["judge_score"] for c in data["continual"]]

    if not baseline_scores or not continual_scores:
        print("  Skipping distribution chart — insufficient data")
        return

    fig, ax = plt.subplots(figsize=(10, 6))

    bins = [0.5, 1.5, 2.5, 3.5, 4.5, 5.5]
    ax.hist(baseline_scores, bins=bins, alpha=0.6, color="#e74c3c", label=f"Baseline (avg: {np.mean(baseline_scores):.2f})", edgecolor="white")
    ax.hist(continual_scores, bins=bins, alpha=0.6, color="#2ecc71", label=f"Continual (avg: {np.mean(continual_scores):.2f})", edgecolor="white")

    ax.set_xlabel("Judge Score", fontsize=12)
    ax.set_ylabel("Count", fontsize=12)
    ax.set_title("Score Distribution: Baseline vs Continual Learning", fontsize=14)
    ax.set_xticks([1, 2, 3, 4, 5])
    ax.legend(fontsize=11)
    ax.grid(True, axis="y", alpha=0.3)

    fig.tight_layout()
    out = OUTPUT_DIR / "score_distribution.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"  Saved: {out}")


def main():
    data, path = load_results()

    summary = data.get("summary") or compute_summary(data)
    # Always recompute counts/averages from raw rows in case summary is stale.
    summary = {**summary, **compute_summary(data)}
    print(f"Loaded: {path}")
    print(f"Loaded results: {summary['baseline_count']} baseline, {summary['continual_count']} continual")
    print(f"  Baseline avg:  {summary['baseline_avg_score']:.2f}")
    print(f"  Continual avg: {summary['continual_avg_score']:.2f}")
    print(f"  Improvement:   {summary['improvement']:+.2f}")
    print()

    print("Generating charts...")
    chart_quality_curve(data)
    chart_skill_growth(data)
    chart_score_distribution(data)
    print("Done.")


if __name__ == "__main__":
    main()
