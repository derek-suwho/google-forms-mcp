from google_forms_mcp.compiler import compile_create_body, compile_item_requests
from google_forms_mcp.models import FormSpec


def sample_spec() -> FormSpec:
    return FormSpec.model_validate(
        {
            "title": "Club RSVP",
            "description": "Respond by Friday",
            "sections": [
                {
                    "title": "Basics",
                    "questions": [
                        {"title": "Name", "type": "short_text", "required": True},
                        {
                            "title": "Transport",
                            "type": "multiple_choice",
                            "options": ["Car", "Bus"],
                        },
                    ],
                },
                {
                    "title": "Feedback",
                    "questions": [
                        {
                            "title": "Rating",
                            "type": "linear_scale",
                            "lower_bound": 1,
                            "upper_bound": 5,
                            "low_label": "Poor",
                            "high_label": "Great",
                        },
                        {"title": "Days", "type": "checkboxes", "options": ["Fri", "Sat"]},
                    ],
                },
            ],
        }
    )


def test_compile_create_body_keeps_title_and_document_title() -> None:
    body = compile_create_body(sample_spec())

    assert body == {"info": {"title": "Club RSVP", "documentTitle": "Club RSVP"}}


def test_compile_item_requests_preserves_order_and_google_question_shapes() -> None:
    requests = compile_item_requests(sample_spec())

    assert len(requests) == 6
    assert [request["createItem"]["location"]["index"] for request in requests] == list(
        range(6)
    )
    assert requests[0]["createItem"]["item"] == {
        "title": "Basics",
        "pageBreakItem": {},
    }
    assert requests[1]["createItem"]["item"]["questionItem"] == {
        "question": {"required": True, "textQuestion": {"paragraph": False}}
    }
    assert requests[2]["createItem"]["item"]["questionItem"]["question"][
        "choiceQuestion"
    ] == {
        "type": "RADIO",
        "options": [{"value": "Car"}, {"value": "Bus"}],
        "shuffle": False,
    }
    assert requests[4]["createItem"]["item"]["questionItem"]["question"][
        "scaleQuestion"
    ] == {"low": 1, "high": 5, "lowLabel": "Poor", "highLabel": "Great"}
    assert requests[5]["createItem"]["item"]["questionItem"]["question"][
        "choiceQuestion"
    ]["type"] == "CHECKBOX"
