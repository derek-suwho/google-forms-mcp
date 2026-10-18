import asyncio
from pathlib import Path

import pytest

from google_forms_mcp import server as server_module
from google_forms_mcp.drafts import DraftNotFound
from google_forms_mcp.models import FormSpec
from google_forms_mcp.patches import RemoveOption, SetRequired
from google_forms_mcp.server import (
    create_form_draft,
    create_google_form,
    get_form_draft,
    mcp,
    patch_form_draft,
    publish_form_draft,
    undo_draft_change,
    update_existing_google_form,
)
from google_forms_mcp.tenant import reset_current_user, set_current_user


def test_mcp_server_exposes_preview_create_and_auth_status_tools() -> None:
    tools = asyncio.run(mcp.list_tools())
    names = {tool.name for tool in tools}

    assert names == {
        "preview_google_form",
        "google_forms_auth_status",
        "create_form_draft",
        "get_form_draft",
        "patch_form_draft",
        "undo_draft_change",
        "publish_form_draft",
        "update_existing_google_form",
    }


def test_preview_tool_schema_requires_a_form_spec() -> None:
    tools = asyncio.run(mcp.list_tools())
    preview = next(tool for tool in tools if tool.name == "preview_google_form")

    assert "spec" in preview.input_schema["properties"]
    assert "spec" in preview.input_schema["required"]


def test_direct_creation_is_disabled_in_favor_of_reviewed_drafts() -> None:
    spec = FormSpec.model_validate(
        {
            "title": "Safe form",
            "sections": [
                {
                    "title": "Questions",
                    "questions": [{"title": "Name", "type": "short_text"}],
                }
            ],
        }
    )

    assert create_google_form(spec, confirm=True) == {
        "status": "use_draft_workflow",
        "message": (
            "Direct creation is disabled. Use create_form_draft, review/patch it, "
            "then publish_form_draft with the reviewed expected_version."
        ),
    }


def test_draft_tools_patch_and_undo_without_google_oauth(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("GOOGLE_FORMS_DRAFT_DB", str(tmp_path / "drafts.db"))
    spec = FormSpec.model_validate(
        {
            "title": "Draft form",
            "sections": [
                {
                    "title": "Questions",
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
    )

    created = create_form_draft(spec)
    patched = patch_form_draft(
        created["draft_id"],
        [RemoveOption(operation="remove_option", question_title="Location", option="NYC")],
    )
    fetched = get_form_draft(created["draft_id"])
    undone = undo_draft_change(created["draft_id"])

    assert patched["version"] == 2
    assert fetched["spec"]["sections"][0]["questions"][0]["options"] == [
        "SF",
        "Seattle",
    ]
    assert undone["version"] == 1
    assert publish_form_draft(created["draft_id"], confirm=False)["status"] == (
        "confirmation_required"
    )
    assert update_existing_google_form("form-id", [], confirm=False)["status"] == "invalid_request"


class RecordingPatchGateway:
    def __init__(self) -> None:
        self.applied: list[object] = []

    def get_form_revision(self, form_id: str) -> str:
        assert form_id == "form-id"
        return "revision-7"

    def patch_form(
        self, form_id: str, operations: list[object], *, expected_revision_id: str
    ) -> dict[str, object]:
        self.applied = operations
        return {
            "status": "updated",
            "form_id": form_id,
            "revision": expected_revision_id,
        }


def test_existing_form_confirmation_token_binds_reviewed_operations(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    gateway = RecordingPatchGateway()
    monkeypatch.setenv("GOOGLE_FORMS_CONFIRMATION_KEY", str(tmp_path / "key"))
    monkeypatch.setattr(server_module, "_google_gateway", lambda: gateway)
    reviewed = [SetRequired(operation="set_required", question_title="Question", required=True)]

    plan = update_existing_google_form("form-id", reviewed, confirm=False)
    updated = update_existing_google_form(
        "form-id",
        [SetRequired(operation="set_required", question_title="Question", required=False)],
        plan_token=plan["plan_token"],
        confirm=True,
    )

    assert updated["status"] == "updated"
    assert len(gateway.applied) == 1
    assert isinstance(gateway.applied[0], SetRequired)
    assert gateway.applied[0].required is True


def test_multiuser_drafts_are_isolated_by_authenticated_tenant(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("GOOGLE_FORMS_MULTIUSER", "true")
    monkeypatch.setenv("GOOGLE_FORMS_MULTIUSER_DATA_DIR", str(tmp_path))
    spec = FormSpec.model_validate(
        {
            "title": "Tenant draft",
            "sections": [
                {
                    "title": "Questions",
                    "questions": [{"title": "Name", "type": "short_text"}],
                }
            ],
        }
    )

    first_context = set_current_user("user-one")
    try:
        first = create_form_draft(spec)
    finally:
        reset_current_user(first_context)

    second_context = set_current_user("user-two")
    try:
        second = create_form_draft(spec)
        with pytest.raises(DraftNotFound):
            get_form_draft(first["draft_id"])
    finally:
        reset_current_user(second_context)

    assert first["draft_id"] != second["draft_id"]
    assert (tmp_path / "tenants" / "user-one" / "drafts.db").exists()
    assert (tmp_path / "tenants" / "user-two" / "drafts.db").exists()
