import pytest

from src.skills.models import Skill, SkillUpdate


def test_create_new_generates_uuid_and_timestamps():
    skill = Skill.create_new(
        title="Test",
        problem="Test problem",
        resolution_md="# Steps",
        embedding=[0.1] * 768,
    )
    assert len(skill.skill_id) == 36  # UUID format
    assert skill.version == 1
    assert skill.confidence == 0.5
    assert skill.created_at == skill.updated_at


def test_create_new_with_all_fields():
    skill = Skill.create_new(
        title="Password Reset",
        problem="Can't log in",
        resolution_md="# Steps\n**Do:** Reset",
        embedding=[0.1] * 768,
        conditions=["locked out"],
        keywords=["password"],
        product_area="auth",
        issue_type="how-to",
    )
    assert skill.title == "Password Reset"
    assert skill.conditions == ["locked out"]
    assert skill.product_area == "auth"


def test_skill_rejects_wrong_embedding_dim():
    with pytest.raises(ValueError, match="embedding dim"):
        Skill.create_new(
            title="Test",
            problem="Test",
            resolution_md="# Steps",
            embedding=[0.1] * 100,  # wrong dim
        )


def test_skill_rejects_empty_embedding():
    with pytest.raises(ValueError):
        Skill.create_new(
            title="Test",
            problem="Test",
            resolution_md="# Steps",
            embedding=[],
        )


def test_to_neo4j_props_returns_dict():
    skill = Skill.create_new(
        title="Test",
        problem="Test",
        resolution_md="# Steps",
        embedding=[0.1] * 768,
    )
    props = skill.to_neo4j_props()
    assert isinstance(props, dict)
    assert props["title"] == "Test"
    assert len(props["embedding"]) == 768


def test_from_neo4j_node_round_trips():
    skill = Skill.create_new(
        title="Test",
        problem="Test",
        resolution_md="# Steps",
        embedding=[0.1] * 768,
    )
    props = skill.to_neo4j_props()
    restored = Skill.from_neo4j_node(props)
    assert restored.skill_id == skill.skill_id
    assert restored.title == skill.title


def test_skill_update_partial():
    update = SkillUpdate(title="New Title")
    assert update.title == "New Title"
    assert update.problem is None
    assert update.embedding is None
