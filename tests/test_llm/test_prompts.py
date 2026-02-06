from src.llm.prompts import EXTRACTION_PROMPT, REFINEMENT_PROMPT


def test_extraction_prompt_has_conversation_placeholder():
    assert "{conversation}" in EXTRACTION_PROMPT


def test_extraction_prompt_requires_do_check_say():
    assert "**Do:**" in EXTRACTION_PROMPT
    assert "**Check:**" in EXTRACTION_PROMPT
    assert "**Say:**" in EXTRACTION_PROMPT


def test_extraction_prompt_requires_json_fields():
    for field in ["title", "problem", "resolution", "conditions", "keywords",
                  "product_area", "issue_type"]:
        assert field in EXTRACTION_PROMPT


def test_refinement_prompt_has_all_placeholders():
    for placeholder in ["{title}", "{problem}", "{resolution}", "{conditions}",
                        "{keywords}", "{conversation}", "{feedback}"]:
        assert placeholder in REFINEMENT_PROMPT


def test_refinement_prompt_requires_changes_field():
    assert "changes" in REFINEMENT_PROMPT


def test_prompts_format_without_error():
    rendered = EXTRACTION_PROMPT.format(conversation="Agent: Hi\nCustomer: Help")
    assert "Agent: Hi" in rendered

    rendered = REFINEMENT_PROMPT.format(
        title="Test",
        problem="Test problem",
        resolution="# Steps",
        conditions="['cond1']",
        keywords="['kw1']",
        conversation="Agent: Hi",
        feedback="worked well",
    )
    assert "Test problem" in rendered
