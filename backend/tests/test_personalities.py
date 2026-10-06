import pytest

from agent.contract import Environment
from agent.personalities import (
    PERSONALITIES,
    SHARED_RULES,
    build_system_prompt,
    get_personality,
)


def test_every_environment_has_a_personality():
    assert set(PERSONALITIES) == set(Environment)


def test_environments_map_to_the_right_role():
    assert get_personality(Environment.LECTURE_HALL).role == "professor"
    assert get_personality(Environment.STUDY_ROOM).role == "tutor"
    assert get_personality(Environment.CAFE).role == "study friend"


@pytest.mark.parametrize("environment", list(Environment))
def test_settings_are_sensible(environment):
    personality = get_personality(environment)
    assert 1 <= personality.segments_per_topic <= 6
    assert 1 <= personality.questions_per_topic <= 3


@pytest.mark.parametrize("environment", list(Environment))
def test_system_prompt_has_persona_and_shared_rules(environment):
    personality = get_personality(environment)
    prompt = build_system_prompt(personality)
    assert personality.persona in prompt
    assert personality.praise_style in prompt
    assert personality.hint_style in prompt
    for rule in SHARED_RULES:
        assert rule in prompt


def test_personalities_have_different_prompts():
    prompts = {build_system_prompt(p) for p in PERSONALITIES.values()}
    assert len(prompts) == len(PERSONALITIES)


def test_only_the_tutor_offers_the_summary():
    assert [e for e in Environment if get_personality(e).offers_summary] == [Environment.STUDY_ROOM]
