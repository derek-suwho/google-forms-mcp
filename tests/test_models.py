import pytest
from pydantic import ValidationError

from google_forms_mcp.models import FormSpec


def test_form_spec_normalizes_a_multisection_form() -> None:
    spec = FormSpec.model_validate(
        {
            "title": "  Retreat RSVP  ",
            "description": "Plan transportation",
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
                    "title": "Details",
                    "questions": [
                        {
                            "title": "Availability",
                            "type": "checkboxes",
                            "options": ["Friday", "Saturday"],
                        }
                    ],
                },
            ],
        }
    )

    assert spec.title == "Retreat RSVP"
    assert spec.question_count == 3
    assert spec.sections[0].questions[0].required is True


def test_choice_question_requires_two_unique_options() -> None:
    with pytest.raises(ValidationError, match="at least two unique options"):
        FormSpec.model_validate(
            {
                "title": "Broken",
                "sections": [
                    {
                        "title": "Questions",
                        "questions": [
                            {"title": "Pick", "type": "dropdown", "options": ["A", "A"]}
                        ],
                    }
                ],
            }
        )


def test_linear_scale_rejects_out_of_range_bounds() -> None:
    with pytest.raises(ValidationError, match="between 0 and 10"):
        FormSpec.model_validate(
            {
                "title": "Broken scale",
                "sections": [
                    {
                        "title": "Questions",
                        "questions": [
                            {
                                "title": "Rate it",
                                "type": "linear_scale",
                                "lower_bound": -1,
                                "upper_bound": 11,
                            }
                        ],
                    }
                ],
            }
        )
