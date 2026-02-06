"""Explore the ABCD dataset structure and print summary statistics.

Pure stdlib — no external deps required.
"""

import gzip
import json
from collections import Counter
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "abcd" / "data"


def load_conversations() -> dict:
    gz_path = DATA_DIR / "abcd_v1.1.json.gz"
    json_path = DATA_DIR / "abcd_v1.1.json"

    if json_path.exists():
        with open(json_path) as f:
            return json.load(f)
    elif gz_path.exists():
        with gzip.open(gz_path, "rt") as f:
            return json.load(f)
    else:
        raise FileNotFoundError(f"No ABCD data found at {DATA_DIR}")


def load_kb() -> dict:
    with open(DATA_DIR / "kb.json") as f:
        return json.load(f)


def load_ontology() -> dict:
    with open(DATA_DIR / "ontology.json") as f:
        return json.load(f)


def analyze_conversations(data: dict):
    print("=" * 60)
    print("ABCD Dataset Summary")
    print("=" * 60)

    total = 0
    for split, convos in data.items():
        total += len(convos)
        print(f"  {split:>5}: {len(convos):,} conversations")
    print(f"  {'total':>5}: {total:,} conversations")

    # Analyze train split
    train = data["train"]
    print(f"\n--- Train Split Analysis ({len(train):,} conversations) ---")

    # Turn counts
    turn_counts = [len(c["original"]) for c in train]
    avg_turns = sum(turn_counts) / len(turn_counts)
    print(f"  Avg turns per conversation: {avg_turns:.1f}")
    print(f"  Min turns: {min(turn_counts)}, Max turns: {max(turn_counts)}")

    # Flow distribution
    flows = Counter(c["scenario"]["flow"] for c in train)
    print(f"\n  Flows ({len(flows)} unique):")
    for flow, count in flows.most_common():
        print(f"    {flow:30s} {count:5d} ({count/len(train)*100:.1f}%)")

    # Subflow distribution
    subflows = Counter(c["scenario"]["subflow"] for c in train)
    print(f"\n  Subflows ({len(subflows)} unique):")
    for subflow, count in subflows.most_common(15):
        print(f"    {subflow:40s} {count:5d} ({count/len(train)*100:.1f}%)")
    if len(subflows) > 15:
        print(f"    ... and {len(subflows) - 15} more")

    # Speaker distribution
    speakers = Counter()
    for c in train:
        for turn in c["original"]:
            speakers[turn[0]] += 1
    print(f"\n  Speaker turns:")
    for speaker, count in speakers.most_common():
        print(f"    {speaker:10s} {count:,}")


def analyze_kb(kb: dict):
    print(f"\n--- Knowledge Base (kb.json) ---")
    print(f"  Total subflows with action sequences: {len(kb)}")

    action_counts = [len(actions) for actions in kb.values()]
    print(f"  Avg actions per subflow: {sum(action_counts)/len(action_counts):.1f}")
    print(f"  Min actions: {min(action_counts)}, Max actions: {max(action_counts)}")

    # Unique actions
    all_actions = set()
    for actions in kb.values():
        all_actions.update(actions)
    print(f"  Unique actions: {len(all_actions)}")
    for action in sorted(all_actions):
        print(f"    - {action}")


def analyze_ontology(ontology: dict):
    print(f"\n--- Ontology (ontology.json) ---")
    print(f"  Top-level keys: {list(ontology.keys())}")

    if "intents" in ontology:
        intents = ontology["intents"]
        flows = intents.get("flows", [])
        subflows_map = intents.get("subflows", {})
        print(f"  Flows: {len(flows)}")
        for flow in flows:
            subs = subflows_map.get(flow, [])
            print(f"    {flow}: {len(subs)} subflows")

    if "actions" in ontology:
        print(f"  Actions defined: {len(ontology['actions'])}")


def cross_reference(data: dict, kb: dict):
    """Check how well conversations map to KB ground truth."""
    print(f"\n--- Cross-Reference: Conversations ↔ KB ---")

    train = data["train"]
    conv_subflows = set(c["scenario"]["subflow"] for c in train)
    kb_subflows = set(kb.keys())

    in_both = conv_subflows & kb_subflows
    conv_only = conv_subflows - kb_subflows
    kb_only = kb_subflows - conv_subflows

    print(f"  Subflows in both conversations and KB: {len(in_both)}")
    print(f"  Subflows in conversations only: {len(conv_only)}")
    if conv_only:
        for s in sorted(conv_only):
            print(f"    - {s}")
    print(f"  Subflows in KB only: {len(kb_only)}")
    if kb_only:
        for s in sorted(kb_only):
            print(f"    - {s}")

    # Show a sample mapping
    print(f"\n  Sample ground truth mappings:")
    for subflow in sorted(in_both)[:5]:
        count = sum(1 for c in train if c["scenario"]["subflow"] == subflow)
        print(f"    {subflow} ({count} convos) → {kb[subflow]}")


def main():
    data = load_conversations()
    kb = load_kb()
    ontology = load_ontology()

    analyze_conversations(data)
    analyze_kb(kb)
    analyze_ontology(ontology)
    cross_reference(data, kb)

    print("\n" + "=" * 60)
    print("Exploration complete.")
    print("=" * 60)


if __name__ == "__main__":
    main()
