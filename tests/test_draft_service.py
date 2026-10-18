from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import TypeAdapter

from google_forms_mcp.draft_service import DraftService, PublishedDraftImmutable
from google_forms_mcp.drafts import DraftStore
from google_forms_mcp.google_gateway import FormCreationError
from google_forms_mcp.models import FormSpec
from google_forms_mcp.patches import PatchOperation

OPERATIONS = TypeAdapter(list[PatchOperation])


class RecordingGateway:
    def __init__(self) -> None:
        self.created: list[FormSpec] = []

    def create_form(self, spec: FormSpec) -> dict[str, Any]:
        self.created.append(spec)
        return {
            "formId": "form-123",
            "editUri": "https://docs.google.com/forms/d/form-123/edit",
            "responderUri": "https://docs.google.com/forms/d/e/response-123/viewform",
        }


class FailingAfterCreationGateway:
    def __init__(self) -> None:
        self.calls = 0

    def create_form(self, spec: FormSpec) -> dict[str, Any]:
        self.calls += 1
        raise FormCreationError(
            "Google form shell exists but population failed",
            form_id="partial-form-456",
            stage="populate",
        )


class FailOnceMarkStore(DraftStore):
    def __init__(self, database: Path) -> None:
        super().__init__(database)
        self.failed = False

    def mark_published(self, draft_id: str, form_id: str, *, expected_version: int):
        if not self.failed:
            self.failed = True
            raise RuntimeError("transient publication-recording failure")
        return super().mark_published(draft_id, form_id, expected_version=expected_version)


def raw_spec() -> dict[str, Any]:
    return {
        "title": "Office tour",
        "sections": [
            {
                "title": "Basics",
                "questions": [
                    {
                        "title": "Location",
                        "type": "multiple_choice",
                        "options": ["SF", "NYC", "Seattle"],
                    }
                ],
            }
        ],
    }


def test_draft_service_create_patch_and_undo(tmp_path: Path) -> None:
    gateway = RecordingGateway()
    service = DraftService(DraftStore(tmp_path / "drafts.db"), gateway)

    created = service.create(raw_spec())
    patched = service.patch(
        created["draft_id"],
        OPERATIONS.validate_python(
            [
                {
                    "operation": "remove_option",
                    "question_title": "Location",
                    "option": "NYC",
                }
            ]
        ),
    )
    restored = service.undo(created["draft_id"])

    assert created["version"] == 1
    assert patched["version"] == 2
    assert patched["spec"]["sections"][0]["questions"][0]["options"] == [
        "SF",
        "Seattle",
    ]
    assert patched["changes"][0]["before"] == "NYC"
    assert restored["version"] == 1
    assert restored["spec"]["sections"][0]["questions"][0]["options"] == [
        "SF",
        "NYC",
        "Seattle",
    ]
    assert gateway.created == []


def test_publish_is_guarded_and_marks_draft_published(tmp_path: Path) -> None:
    gateway = RecordingGateway()
    service = DraftService(DraftStore(tmp_path / "drafts.db"), gateway)
    draft = service.create(raw_spec())

    blocked = service.publish(draft["draft_id"], confirm=False)
    missing_version = service.publish(draft["draft_id"], confirm=True)
    conflict = service.publish(draft["draft_id"], confirm=True, expected_version=99)
    published = service.publish(draft["draft_id"], confirm=True, expected_version=1)
    repeated = service.publish(draft["draft_id"], confirm=True, expected_version=1)
    fetched = service.get(draft["draft_id"])

    assert blocked["status"] == "confirmation_required"
    assert blocked["version"] == 1
    assert blocked["spec"]["title"] == "Office tour"
    assert missing_version["status"] == "expected_version_required"
    assert conflict == {
        "status": "version_conflict",
        "draft_id": draft["draft_id"],
        "expected_version": 99,
        "current_version": 1,
        "message": "The draft changed after review. Review the current version before publishing.",
    }
    assert len(gateway.created) == 1
    assert gateway.created[0].title == "Office tour"
    assert published["status"] == "published"
    assert published["form_id"] == "form-123"
    assert repeated == {
        "status": "already_published",
        "draft_id": draft["draft_id"],
        "form_id": "form-123",
        "message": "This draft is already linked to a published Google Form.",
    }
    with pytest.raises(PublishedDraftImmutable):
        service.patch(
            draft["draft_id"],
            OPERATIONS.validate_python(
                [
                    {
                        "operation": "set_form_title",
                        "new_title": "Should use existing-form update",
                    }
                ]
            ),
        )
    with pytest.raises(PublishedDraftImmutable):
        service.undo(draft["draft_id"])
    assert fetched["published_form_id"] == "form-123"
    assert fetched["status"] == "published"


def test_partial_google_creation_is_recorded_and_not_retried(tmp_path: Path) -> None:
    gateway = FailingAfterCreationGateway()
    service = DraftService(DraftStore(tmp_path / "drafts.db"), gateway)
    draft = service.create(raw_spec())

    with pytest.raises(FormCreationError):
        service.publish(draft["draft_id"], confirm=True, expected_version=1)

    failed = service.get(draft["draft_id"])
    repeated = service.publish(draft["draft_id"], confirm=True, expected_version=1)
    assert failed["status"] == "publication_failed"
    assert failed["published_form_id"] == "partial-form-456"
    assert repeated["status"] == "publication_failed"
    assert gateway.calls == 1


def test_local_recording_failure_after_google_success_blocks_duplicate_retry(
    tmp_path: Path,
) -> None:
    gateway = RecordingGateway()
    service = DraftService(FailOnceMarkStore(tmp_path / "drafts.db"), gateway)
    draft = service.create(raw_spec())

    with pytest.raises(RuntimeError, match="recording failure"):
        service.publish(draft["draft_id"], confirm=True, expected_version=1)

    failed = service.get(draft["draft_id"])
    repeated = service.publish(draft["draft_id"], confirm=True, expected_version=1)
    assert failed["status"] == "publication_failed"
    assert failed["published_form_id"] == "form-123"
    assert repeated["status"] == "publication_failed"
    assert len(gateway.created) == 1
