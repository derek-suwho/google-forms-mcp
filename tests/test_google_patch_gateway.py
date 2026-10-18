from __future__ import annotations

from typing import Any

import pytest
from pydantic import TypeAdapter

from google_forms_mcp.google_gateway import FormRevisionConflict, GoogleFormsGateway
from google_forms_mcp.patches import PatchOperation

OPERATIONS = TypeAdapter(list[PatchOperation])


class Executable:
    def __init__(self, result: dict[str, Any]) -> None:
        self.result = result

    def execute(self) -> dict[str, Any]:
        return self.result


class FakeFormsResource:
    def __init__(self) -> None:
        self.batch_calls: list[tuple[str, dict[str, Any]]] = []
        self.form = {
            "formId": "form-1",
            "revisionId": "revision-1",
            "info": {"title": "Office tour", "description": "Old"},
            "items": [
                {"itemId": "section-1", "title": "Basics", "pageBreakItem": {}},
                {
                    "itemId": "question-1",
                    "title": "Office location",
                    "questionItem": {
                        "question": {
                            "questionId": "qid-1",
                            "required": True,
                            "choiceQuestion": {
                                "type": "RADIO",
                                "options": [
                                    {"value": "SF"},
                                    {"value": "NYC"},
                                    {"value": "Seattle"},
                                ],
                                "shuffle": False,
                            },
                        }
                    },
                },
                {
                    "itemId": "question-2",
                    "title": "Notes",
                    "questionItem": {
                        "question": {
                            "questionId": "qid-2",
                            "required": False,
                            "textQuestion": {"paragraph": True},
                        }
                    },
                },
            ],
        }

    def get(self, *, formId: str) -> Executable:
        assert formId == "form-1"
        return Executable(self.form)

    def batchUpdate(self, *, formId: str, body: dict[str, Any]) -> Executable:
        self.batch_calls.append((formId, body))
        return Executable({})


class FakeGoogleService:
    def __init__(self) -> None:
        self.resource = FakeFormsResource()

    def forms(self) -> FakeFormsResource:
        return self.resource


def test_patch_existing_form_emits_targeted_update_requests() -> None:
    google = FakeGoogleService()
    gateway = GoogleFormsGateway(google)
    operations = OPERATIONS.validate_python(
        [
            {
                "operation": "remove_option",
                "question_title": "Office location",
                "option": "NYC",
            },
            {
                "operation": "add_option",
                "question_title": "Office location",
                "option": "Other",
            },
            {
                "operation": "set_required",
                "question_title": "Office location",
                "required": False,
            },
            {
                "operation": "rename_question",
                "question_title": "Notes",
                "new_title": "Additional notes",
            },
        ]
    )

    result = gateway.patch_form("form-1", operations, expected_revision_id="revision-1")

    _, body = google.resource.batch_calls[0]
    assert body["includeFormInResponse"] is True
    assert body["writeControl"] == {"requiredRevisionId": "revision-1"}
    requests = body["requests"]
    assert len(requests) == 4
    choice_options = requests[1]["updateItem"]["item"]["questionItem"]["question"][
        "choiceQuestion"
    ]["options"]
    assert choice_options == [{"value": "SF"}, {"value": "Seattle"}, {"value": "Other"}]
    assert requests[2]["updateItem"]["item"]["questionItem"]["question"]["required"] is False
    assert requests[3]["updateItem"]["item"]["title"] == "Additional notes"
    assert result["status"] == "updated"
    assert result["applied_operations"] == 4


def test_patch_existing_form_supports_structural_and_form_info_changes() -> None:
    google = FakeGoogleService()
    gateway = GoogleFormsGateway(google)
    operations = OPERATIONS.validate_python(
        [
            {"operation": "set_form_title", "new_title": "Updated tour"},
            {
                "operation": "rename_section",
                "section_title": "Basics",
                "new_title": "Attendee details",
            },
            {"operation": "delete_question", "question_title": "Notes"},
            {
                "operation": "add_question",
                "section_title": "Attendee details",
                "question": {"title": "Email", "type": "short_text", "required": True},
            },
        ]
    )

    gateway.patch_form("form-1", operations, expected_revision_id="revision-1")

    requests = google.resource.batch_calls[0][1]["requests"]
    assert requests[0]["updateFormInfo"]["info"]["title"] == "Updated tour"
    assert requests[1]["updateItem"]["item"]["title"] == "Attendee details"
    assert requests[2] == {"deleteItem": {"location": {"index": 2}}}
    assert requests[3]["createItem"]["item"]["title"] == "Email"
    assert requests[3]["createItem"]["location"]["index"] == 2


def test_existing_form_update_requires_the_reviewed_google_revision() -> None:
    google = FakeGoogleService()
    gateway = GoogleFormsGateway(google)
    operations = OPERATIONS.validate_python(
        [
            {
                "operation": "set_required",
                "question_title": "Office location",
                "required": False,
            }
        ]
    )

    assert gateway.get_form_revision("form-1") == "revision-1"
    with pytest.raises(FormRevisionConflict, match="expected revision stale"):
        gateway.patch_form("form-1", operations, expected_revision_id="stale")
    assert google.resource.batch_calls == []
