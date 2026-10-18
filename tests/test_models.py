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
                        "questions": [{"title": "Pick", "type": "dropdown", "options": ["A", "A"]}],
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


def test_whitespace_only_titles_and_options_are_rejected_after_normalization() -> None:
    with pytest.raises(ValidationError):
        FormSpec.model_validate(
            {
                "title": "   ",
                "sections": [
                    {
                        "title": "Questions",
                        "questions": [{"title": "Name", "type": "short_text"}],
                    }
                ],
            }
        )

    with pytest.raises(ValidationError, match="at least two unique options"):
        FormSpec.model_validate(
            {
                "title": "Choices",
                "sections": [
                    {
                        "title": "Questions",
                        "questions": [
                            {
                                "title": "Pick",
                                "type": "multiple_choice",
                                "options": ["A", "   "],
                            }
                        ],
                    }
                ],
            }
        )


def test_duplicate_selector_titles_are_rejected() -> None:
    with pytest.raises(ValidationError, match="Section titles must be unique"):
        FormSpec.model_validate(
            {
                "title": "Duplicate sections",
                "sections": [
                    {
                        "title": "Same",
                        "questions": [{"title": "One", "type": "short_text"}],
                    },
                    {
                        "title": "Same",
                        "questions": [{"title": "Two", "type": "short_text"}],
                    },
                ],
            }
        )

    with pytest.raises(ValidationError, match="Question titles must be unique"):
        FormSpec.model_validate(
            {
                "title": "Duplicate questions",
                "sections": [
                    {
                        "title": "First",
                        "questions": [{"title": "Same", "type": "short_text"}],
                    },
                    {
                        "title": "Second",
                        "questions": [{"title": "Same", "type": "paragraph"}],
                    },
                ],
            }
        )
