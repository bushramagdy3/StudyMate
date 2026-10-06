import pytest
from pydantic import TypeAdapter, ValidationError

from agent.contract import (
    AnswerEvent,
    Awaiting,
    AvatarState,
    Environment,
    GoToTopicEvent,
    RaiseHandEvent,
    RepeatEvent,
    StartSessionRequest,
    StudentEvent,
    SummaryEvent,
    TeacherResponse,
    Topic,
)

events = TypeAdapter(StudentEvent)

OUTLINE = [
    Topic(index=0, title="HTTP Versions"),
    Topic(index=1, title="Head-of-Line Blocking"),
]


def test_start_request_from_json():
    request = StartSessionRequest.model_validate_json(
        '{"environment": "cafe", "lecture": [{"slide": 1, "text": "HTTP/1.1"}]}'
    )
    assert request.environment is Environment.CAFE
    assert request.lecture[0].text == "HTTP/1.1"


@pytest.mark.parametrize(
    "payload",
    [
        {"environment": "beach", "lecture": [{"slide": 1, "text": "x"}]},
        {"environment": "cafe", "lecture": []},
        {"environment": "cafe", "lecture": [{"slide": 0, "text": "x"}]},
    ],
)
def test_start_request_rejects_bad_input(payload):
    with pytest.raises(ValidationError):
        StartSessionRequest.model_validate(payload)


@pytest.mark.parametrize(
    "payload, expected",
    [
        ({"type": "answer", "text": "  multiplexing  "}, AnswerEvent(text="multiplexing")),
        ({"type": "raise_hand", "segment_index": 2}, RaiseHandEvent(segment_index=2)),
        ({"type": "go_to_topic", "topic_index": 0}, GoToTopicEvent(topic_index=0)),
        ({"type": "repeat", "topic_index": 2}, RepeatEvent(topic_index=2)),
        ({"type": "summary"}, SummaryEvent()),
    ],
)
def test_events_parse_by_type(payload, expected):
    assert events.validate_python(payload) == expected


@pytest.mark.parametrize(
    "payload",
    [
        {"type": "dance"},
        {"type": "answer", "text": "   "},
        {"type": "raise_hand"},
        {"type": "back"},  # no back button
        {"type": "end"},  # ending is Teacher.end_session(), not an event
        {"type": "repeat"},  # which topic to repeat is required
        {"type": "continue", "extra": 1},
    ],
)
def test_events_reject_bad_input(payload):
    with pytest.raises(ValidationError):
        events.validate_python(payload)


def make_response(**overrides):
    fields = dict(
        session_id="abc",
        speech=["Welcome!", "Today we cover HTTP."],
        avatar_state=AvatarState.SPEAKING,
        awaiting=Awaiting.CONTINUE,
        outline=OUTLINE,
        current_topic=0,
    )
    return TeacherResponse(**(fields | overrides))


def test_response_json_round_trip():
    response = make_response(completed_topics=[0])
    assert TeacherResponse.model_validate_json(response.model_dump_json()) == response


@pytest.mark.parametrize("overrides", [{"current_topic": 2}, {"completed_topics": [0, 5]}])
def test_response_rejects_topics_outside_outline(overrides):
    with pytest.raises(ValidationError):
        make_response(**overrides)
