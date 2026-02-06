"""Pure heuristic functions for determining ABCD conversation resolution.

Ground truth: data/abcd/data/kb.json maps subflows to expected action sequences.
Action extraction: conversation["delexed"] turns where targets[1] == "take_action".
"""

import re


def extract_actions(conversation: dict) -> list[str]:
    """Extract action names from delexed turns where targets[1] == 'take_action'."""
    actions = []
    for turn in conversation.get("delexed", []):
        targets = turn.get("targets", [])
        if len(targets) >= 3 and targets[1] == "take_action" and targets[2]:
            actions.append(targets[2])
    return actions


def compute_action_match(actual: list[str], expected: list[str]) -> float:
    """Fraction of expected actions present in actual. Order-independent."""
    if not expected:
        return 0.0
    actual_set = set(actual)
    matched = sum(1 for a in expected if a in actual_set)
    return matched / len(expected)


def check_escalation(conversation: dict) -> bool:
    """Check last few turns for escalation signals."""
    escalation_words = {"transfer", "supervisor", "escalate", "manager"}
    delexed = conversation.get("delexed", [])
    # Check last 5 turns
    for turn in delexed[-5:]:
        text = turn.get("text", "").lower()
        if any(w in text for w in escalation_words):
            return True
    return False


def check_sentiment(conversation: dict) -> bool:
    """Check last customer utterance for positive signals."""
    positive_signals = {"thank", "thanks", "great", "perfect", "awesome", "wonderful",
                        "that worked", "appreciate", "excellent", "solved"}
    delexed = conversation.get("delexed", [])
    # Find last customer utterance
    for turn in reversed(delexed):
        if turn.get("speaker") == "customer":
            text = turn.get("text", "").lower()
            return any(s in text for s in positive_signals)
    return False


def normalize_subflow(subflow: str) -> str:
    """Strip numeric suffixes (e.g. 'timing_4' -> 'timing') to match kb.json keys."""
    return re.sub(r"_\d+$", "", subflow)


def determine_resolution(conversation: dict, kb: dict) -> bool | None:
    """Combined heuristic. Returns True (resolved), False (unresolved), or None (unknown subflow).

    Resolution logic:
    1. Look up subflow in KB (normalize first)
    2. If subflow not in KB -> None (skip)
    3. Action match >= 0.8 and no escalation -> True
    4. Action match in [0.5, 0.8) and positive sentiment -> True
    5. Otherwise -> False
    """
    # Get subflow — prefer delexed[0].targets[0] as canonical (already normalized)
    delexed = conversation.get("delexed", [])
    scenario_subflow = conversation.get("scenario", {}).get("subflow", "")

    canonical = None
    if delexed and len(delexed[0].get("targets", [])) >= 1:
        canonical = delexed[0]["targets"][0]

    # Try canonical first, then normalized scenario subflow
    if canonical and canonical in kb:
        subflow = canonical
    else:
        subflow = normalize_subflow(scenario_subflow)

    if subflow not in kb:
        return None

    expected_actions = kb[subflow]
    actual_actions = extract_actions(conversation)
    match_ratio = compute_action_match(actual_actions, expected_actions)

    if match_ratio >= 0.8 and not check_escalation(conversation):
        return True

    if 0.5 <= match_ratio < 0.8 and not check_escalation(conversation) and check_sentiment(conversation):
        return True

    return False
