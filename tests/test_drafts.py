from __future__ import annotations

from pathlib import Path

import pytest

from google_forms_mcp.drafts import (
    DraftConflict,
    DraftNotFound,
    DraftStore,
    NothingToUndo,
)
from google_forms_mcp.models import FormSpec


def form_spec(title: str = "Event RSVP") -> FormSpec:
    return FormSpec.model_validate(
        {
            "title": title,
            "sections": [
                {
                    "title": "Basics",
                    "questions": [{"title": "Name", "type": "short_text"}],
                }
            ],
        }
    )


def test_create_and_reopen_persistent_draft(tmp_path: Path) -> None:
    database = tmp_path / "drafts.db"
    first = DraftStore(database)

    created = first.create(form_spec())
    reopened = DraftStore(database).get(created.draft_id)

    assert created.version == 1
    assert reopened.draft_id == created.draft_id
    assert reopened.spec.title == "Event RSVP"
    assert reopened.published_form_id is None
    assert database.stat().st_mode & 0o777 == 0o600


def test_save_revision_increments_version_and_undo_restores_previous_spec(
    tmp_path: Path,
) -> None:
    store = DraftStore(tmp_path / "drafts.db")
    created = store.create(form_spec())

    changed = store.save_revision(
        created.draft_id,
        form_spec("Updated RSVP"),
        changes=[{"operation": "set_form_title", "new_title": "Updated RSVP"}],
        expected_version=1,
    )
    restored = store.undo(created.draft_id)

    assert changed.version == 2
    assert changed.spec.title == "Updated RSVP"
    assert restored.version == 1
    assert restored.spec.title == "Event RSVP"


def test_new_revision_after_undo_discards_abandoned_future(tmp_path: Path) -> None:
    store = DraftStore(tmp_path / "drafts.db")
    created = store.create(form_spec())
    store.save_revision(created.draft_id, form_spec("Version 2"), changes=[], expected_version=1)
    store.undo(created.draft_id)

    replacement = store.save_revision(
        created.draft_id,
        form_spec("Alternative Version 2"),
        changes=[],
        expected_version=1,
    )

    assert replacement.version == 2
    assert replacement.spec.title == "Alternative Version 2"
    with pytest.raises(NothingToUndo):
        store.undo(store.create(form_spec()).draft_id)


def test_stale_revision_is_rejected_instead_of_overwriting_newer_changes(
    tmp_path: Path,
) -> None:
    store = DraftStore(tmp_path / "drafts.db")
    created = store.create(form_spec())
    store.save_revision(created.draft_id, form_spec("First edit"), changes=[], expected_version=1)

    with pytest.raises(DraftConflict, match="expected version 1"):
        store.save_revision(
            created.draft_id,
            form_spec("Stale competing edit"),
            changes=[],
            expected_version=1,
        )

    assert store.get(created.draft_id).spec.title == "First edit"


def test_missing_draft_and_published_form_are_reported(tmp_path: Path) -> None:
    store = DraftStore(tmp_path / "drafts.db")

    with pytest.raises(DraftNotFound, match="missing"):
        store.get("missing")

    created = store.create(form_spec())
    assert store.claim_publication(created.draft_id, expected_version=1) is True
    assert store.claim_publication(created.draft_id, expected_version=1) is False
    with pytest.raises(DraftConflict, match="publication"):
        store.save_revision(
            created.draft_id,
            form_spec("Racing edit"),
            changes=[],
            expected_version=1,
        )
    with pytest.raises(DraftConflict, match="publication"):
        store.undo(created.draft_id)
    store.release_publication(created.draft_id, expected_version=1)
    assert store.claim_publication(created.draft_id, expected_version=1) is True
    published = store.mark_published(created.draft_id, "google-form-123", expected_version=1)
    assert published.published_form_id == "google-form-123"
