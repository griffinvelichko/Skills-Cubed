"""Unit tests for resolution heuristic — pure functions, no external deps."""

import pytest

from src.eval.resolution import (
    extract_actions,
    compute_action_match,
    check_escalation,
    check_sentiment,
    normalize_subflow,
    determine_resolution,
)


# --- Helpers to build synthetic ABCD conversation dicts ---

def _make_turn(speaker, text, targets=None):
    return {
        "speaker": speaker,
        "text": text,
        "targets": targets or [None, None, None, [], -1],
    }


def _action_turn(subflow, action_name):
    return _make_turn("action", f"performing {action_name}", [subflow, "take_action", action_name, [], -1])


def _customer_turn(subflow, text):
    return _make_turn("customer", text, [subflow, None, None, [], -1])


def _agent_turn(subflow, text):
    return _make_turn("agent", text, [subflow, "retrieve_utterance", None, [], 5])


def _make_conversation(subflow, delexed, scenario_subflow=None):
    return {
        "scenario": {"subflow": scenario_subflow or subflow},
        "delexed": delexed,
    }


# --- KB fixture ---

SAMPLE_KB = {
    "return_size": ["pull-up-account", "validate-purchase", "membership", "enter-details", "update-order"],
    "refund_status": ["pull-up-account", "validate-purchase", "notify-team", "update-order"],
    "timing": ["search-faq", "search-timing", "select-faq"],
    "recover_username": ["pull-up-account", "verify-identity"],
}


# --- extract_actions ---

def test_extract_actions():
    delexed = [
        _agent_turn("return_size", "hi"),
        _customer_turn("return_size", "hi, i need help"),
        _action_turn("return_size", "pull-up-account"),
        _action_turn("return_size", "validate-purchase"),
        _agent_turn("return_size", "thanks!"),
    ]
    conv = _make_conversation("return_size", delexed)
    assert extract_actions(conv) == ["pull-up-account", "validate-purchase"]


def test_extract_actions_empty():
    conv = _make_conversation("timing", [
        _agent_turn("timing", "hi"),
        _customer_turn("timing", "hello"),
    ])
    assert extract_actions(conv) == []


# --- compute_action_match ---

def test_action_match_full():
    expected = ["pull-up-account", "verify-identity"]
    actual = ["verify-identity", "pull-up-account"]
    assert compute_action_match(actual, expected) == 1.0


def test_action_match_partial():
    expected = ["pull-up-account", "validate-purchase", "membership", "enter-details"]
    actual = ["pull-up-account", "validate-purchase"]
    assert compute_action_match(actual, expected) == 0.5


def test_action_match_empty_expected():
    assert compute_action_match(["pull-up-account"], []) == 0.0


def test_action_match_empty_actual():
    assert compute_action_match([], ["pull-up-account", "verify-identity"]) == 0.0


# --- check_escalation ---

def test_escalation_detected():
    delexed = [
        _agent_turn("return_size", "let me help"),
        _customer_turn("return_size", "this is not working"),
        _agent_turn("return_size", "i can escalate to my manager if you'd like"),
        _customer_turn("return_size", "yes please"),
    ]
    conv = _make_conversation("return_size", delexed)
    assert check_escalation(conv) is True


def test_no_escalation():
    delexed = [
        _agent_turn("timing", "hi"),
        _customer_turn("timing", "when do promo codes expire?"),
        _agent_turn("timing", "they expire after 7 days"),
        _customer_turn("timing", "perfect, thanks!"),
    ]
    conv = _make_conversation("timing", delexed)
    assert check_escalation(conv) is False


# --- check_sentiment ---

def test_sentiment_positive():
    delexed = [
        _agent_turn("timing", "here is the info"),
        _customer_turn("timing", "thank you so much!"),
    ]
    conv = _make_conversation("timing", delexed)
    assert check_sentiment(conv) is True


def test_sentiment_negative():
    delexed = [
        _agent_turn("return_size", "sorry we can't help"),
        _customer_turn("return_size", "this is terrible service"),
    ]
    conv = _make_conversation("return_size", delexed)
    assert check_sentiment(conv) is False


# --- normalize_subflow ---

def test_normalize_subflow_with_suffix():
    assert normalize_subflow("timing_4") == "timing"


def test_normalize_subflow_no_suffix():
    assert normalize_subflow("return_size") == "return_size"


def test_normalize_subflow_multi_digit():
    assert normalize_subflow("policy_12") == "policy"


# --- determine_resolution ---

def test_determine_resolution_full_match():
    """Resolved when action match >= 0.8 and no escalation."""
    delexed = [
        _agent_turn("recover_username", "hi"),
        _action_turn("recover_username", "pull-up-account"),
        _action_turn("recover_username", "verify-identity"),
        _customer_turn("recover_username", "thanks!"),
    ]
    conv = _make_conversation("recover_username", delexed)
    assert determine_resolution(conv, SAMPLE_KB) is True


def test_determine_resolution_escalation_overrides():
    """Unresolved despite good action match if escalation detected."""
    delexed = [
        _agent_turn("recover_username", "hi"),
        _action_turn("recover_username", "pull-up-account"),
        _action_turn("recover_username", "verify-identity"),
        _agent_turn("recover_username", "let me transfer you to a supervisor"),
        _customer_turn("recover_username", "ok"),
    ]
    conv = _make_conversation("recover_username", delexed)
    assert determine_resolution(conv, SAMPLE_KB) is False


def test_determine_resolution_partial_with_sentiment():
    """Resolved with partial match (0.5 <= match < 0.8) + positive sentiment."""
    # refund_status expects 4 actions, providing 2 = 0.5 match
    delexed = [
        _agent_turn("refund_status", "hi"),
        _action_turn("refund_status", "pull-up-account"),
        _action_turn("refund_status", "validate-purchase"),
        _customer_turn("refund_status", "great, thanks for your help!"),
    ]
    conv = _make_conversation("refund_status", delexed)
    assert determine_resolution(conv, SAMPLE_KB) is True


def test_determine_resolution_partial_with_escalation():
    """Unresolved when partial match + positive sentiment but escalation detected."""
    # refund_status expects 4 actions, providing 2 = 0.5 match
    delexed = [
        _agent_turn("refund_status", "hi"),
        _action_turn("refund_status", "pull-up-account"),
        _action_turn("refund_status", "validate-purchase"),
        _agent_turn("refund_status", "let me transfer you to a supervisor"),
        _customer_turn("refund_status", "great, thanks for your help!"),
    ]
    conv = _make_conversation("refund_status", delexed)
    assert determine_resolution(conv, SAMPLE_KB) is False


def test_determine_resolution_unknown_subflow():
    """Returns None when subflow not in KB."""
    delexed = [
        _agent_turn("nonexistent_flow", "hi"),
        _customer_turn("nonexistent_flow", "hello"),
    ]
    conv = _make_conversation("nonexistent_flow", delexed, scenario_subflow="nonexistent_flow")
    assert determine_resolution(conv, SAMPLE_KB) is None


def test_determine_resolution_normalized_subflow():
    """Matches via normalize_subflow when scenario has numeric suffix."""
    delexed = [
        _agent_turn("timing", "hi"),
        _action_turn("timing", "search-faq"),
        _action_turn("timing", "search-timing"),
        _action_turn("timing", "select-faq"),
        _customer_turn("timing", "perfect, thanks!"),
    ]
    conv = _make_conversation("timing", delexed, scenario_subflow="timing_4")
    assert determine_resolution(conv, SAMPLE_KB) is True
