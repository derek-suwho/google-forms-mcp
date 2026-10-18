from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from google_forms_mcp.models import FormSpec
from google_forms_mcp.patches import (
    PatchOperation,
    PatchTargetError,
    apply_patches,
)

OPERATIONS = TypeAdapter(list[PatchOperation])


def sample_spec() -> FormSpec:
    return FormSpec.model_validate(
        {
            "title": "Office tour",
            "description": "Original description",
            "sections": [
                {
                    "title": "Basics",
                    "questions": [
                        {"title": "Name", "type": "short_text", "required": True},
                        {
                            "title": "Office location",
                            "type": "multiple_choice",
                            "options": ["San Francisco", "New York", "Seattle"],
                        },
                        {
                            "title": "Dietary restrictions",
                            "type": "multiple_choice",
                            "required": True,
                            "options": ["None", "Vegetarian", "Vegan"],
                        },
                    ],
                },
                {
                    "title": "Notes",
                    "questions": [{"title": "Anything else?", "type": "paragraph"}],
                },
            ],
        }
    )


def test_targeted_patch_changes_only_requested_fields() -> None:
    operations = OPERATIONS.validate_python(
        [
            {
                "operation": "remove_option",
                "question_title": "Office location",
                "option": "New York",
            },
            {
                "operation": "set_required",
                "question_title": "Dietary restrictions",
                "required": False,
            },
            {
                "operation": "add_option",
                "question_title": "Dietary restrictions",
                "option": "Other",
            },
        ]
    )

    result = apply_patches(sample_spec(), operations)

    office = result.spec.sections[0].questions[1]
    dietary = result.spec.sections[0].questions[2]
    assert office.options == ["San Francisco", "Seattle"]
    assert dietary.required is False
    assert dietary.options == ["None", "Vegetarian", "Vegan", "Other"]
    assert result.spec.sections[0].questions[0].title == "Name"
    assert result.spec.sections[1] == sample_spec().sections[1]
    assert len(result.changes) == 3


def test_patch_supports_titles_descriptions_questions_and_sections() -> None:
    operations = OPERATIONS.validate_python(
        [
            {"operation": "set_form_title", "new_title": "Updated tour"},
            {"operation": "set_form_description", "description": "New description"},
            {
                "operation": "rename_question",
                "question_title": "Anything else?",
                "new_title": "Additional notes",
            },
            {
                "operation": "set_question_description",
                "question_title": "Name",
                "description": "Use your legal name",
            },
            {
                "operation": "rename_section",
                "section_title": "Notes",
                "new_title": "Optional notes",
            },
            {
                "operation": "add_question",
                "section_title": "Optional notes",
                "question": {"title": "Contact email", "type": "short_text"},
            },
            {"operation": "delete_question", "question_title": "Office location"},
        ]
    )

    result = apply_patches(sample_spec(), operations)

    assert result.spec.title == "Updated tour"
    assert result.spec.description == "New description"
    assert result.spec.sections[0].questions[0].description == "Use your legal name"
    assert result.spec.sections[1].title == "Optional notes"
    assert [question.title for question in result.spec.sections[1].questions] == [
        "Additional notes",
        "Contact email",
    ]
    assert all(
        question.title != "Office location"
        for section in result.spec.sections
        for question in section.questions
    )


def test_patch_rejects_missing_targets_duplicate_options_and_too_few_choices() -> None:
    with pytest.raises(PatchTargetError, match="Missing"):
        apply_patches(
            sample_spec(),
            OPERATIONS.validate_python(
                [
                    {
                        "operation": "set_required",
                        "question_title": "Missing",
                        "required": True,
                    }
                ]
            ),
        )

    with pytest.raises(PatchTargetError, match="already exists"):
        apply_patches(
            sample_spec(),
            OPERATIONS.validate_python(
                [
                    {
                        "operation": "add_option",
                        "question_title": "Office location",
                        "option": "Seattle",
                    }
                ]
            ),
        )

    two_choice = FormSpec.model_validate(
        {
            "title": "Two",
            "sections": [
                {
                    "title": "Only",
                    "questions": [{"title": "Pick", "type": "dropdown", "options": ["A", "B"]}],
                }
            ],
        }
    )
    with pytest.raises(PatchTargetError, match="at least two"):
        apply_patches(
            two_choice,
            OPERATIONS.validate_python(
                [{"operation": "remove_option", "question_title": "Pick", "option": "A"}]
            ),
        )


def test_patch_operation_schema_rejects_irrelevant_fields() -> None:
    with pytest.raises(ValidationError):
        OPERATIONS.validate_python(
            [
                {
                    "operation": "set_required",
                    "question_title": "Name",
                    "required": True,
                    "option": "not allowed",
                }
            ]
        )


def test_empty_operation_lists_and_whitespace_values_are_rejected() -> None:
    with pytest.raises(PatchTargetError, match="(?i)at least one"):
        apply_patches(sample_spec(), [])

    with pytest.raises(ValidationError):
        OPERATIONS.validate_python(
            [
                {
                    "operation": "add_option",
                    "question_title": "Office location",
                    "option": "   ",
                }
            ]
        )

    with pytest.raises(ValidationError):
        OPERATIONS.validate_python(
            [
                {
                    "operation": "rename_question",
                    "question_title": "Anything else?",
                    "new_title": "   ",
                }
            ]
        )
