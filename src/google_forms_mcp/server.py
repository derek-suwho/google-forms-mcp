from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from googleapiclient.discovery import build
from mcp.server.mcpserver import MCPServer
from pydantic import TypeAdapter

from google_forms_mcp.auth import authorization_status, credential_paths, load_credentials
from google_forms_mcp.confirmation import ConfirmationSigner, InvalidConfirmationPlan
from google_forms_mcp.draft_service import DraftService
from google_forms_mcp.drafts import DraftStore
from google_forms_mcp.google_gateway import GoogleFormsGateway
from google_forms_mcp.models import FormSpec
from google_forms_mcp.patches import PatchOperation
from google_forms_mcp.service import FormService

mcp = MCPServer(
    name="google-forms",
    instructions=(
        "Prefer persistent drafts for new forms: create_form_draft, targeted patch operations, "
        "then publish_form_draft with confirm=true only after explicit approval. Use "
        "update_existing_google_form for narrow edits to a published form."
    ),
)

_PATCH_OPERATIONS_ADAPTER = TypeAdapter(list[PatchOperation])


class _PreviewOnlyGateway:
    def create_form(self, spec: FormSpec) -> dict[str, Any]:
        raise RuntimeError("The preview tool never creates forms.")


def _google_gateway() -> GoogleFormsGateway:
    credentials = load_credentials()
    google = build("forms", "v1", credentials=credentials, cache_discovery=False)
    return GoogleFormsGateway(google)


def _draft_database() -> Path:
    configured = os.environ.get("GOOGLE_FORMS_DRAFT_DB")
    if configured:
        return Path(configured).expanduser()
    _, token_path = credential_paths()
    return token_path.parent / "drafts.db"


def _confirmation_signer() -> ConfirmationSigner:
    configured = os.environ.get("GOOGLE_FORMS_CONFIRMATION_KEY")
    key_path = (
        Path(configured).expanduser()
        if configured
        else _draft_database().parent / "confirmation.key"
    )
    return ConfirmationSigner(key_path)


def _draft_service(*, with_google: bool = False) -> DraftService:
    gateway = _google_gateway() if with_google else _PreviewOnlyGateway()
    return DraftService(DraftStore(_draft_database()), gateway)


@mcp.tool()
def preview_google_form(spec: FormSpec) -> dict[str, Any]:
    """Validate and preview a Google Form without creating or saving anything."""
    return FormService(_PreviewOnlyGateway()).preview(spec.model_dump(exclude_computed_fields=True))


def create_google_form(spec: FormSpec, confirm: bool = False) -> dict[str, Any]:
    """Deprecated direct creation path; use the reviewed draft workflow."""
    return {
        "status": "use_draft_workflow",
        "message": (
            "Direct creation is disabled. Use create_form_draft, review/patch it, "
            "then publish_form_draft with the reviewed expected_version."
        ),
    }


@mcp.tool()
def create_form_draft(spec: FormSpec) -> dict[str, Any]:
    """Save a persistent, versioned form draft without creating a Google Form."""
    return _draft_service().create(spec.model_dump(exclude_computed_fields=True))


@mcp.tool()
def get_form_draft(draft_id: str) -> dict[str, Any]:
    """Return the current version of a persistent form draft."""
    return _draft_service().get(draft_id)


@mcp.tool()
def patch_form_draft(draft_id: str, operations: list[PatchOperation]) -> dict[str, Any]:
    """Apply targeted operations to a draft while preserving unrelated content."""
    return _draft_service().patch(draft_id, operations)


@mcp.tool()
def undo_draft_change(draft_id: str) -> dict[str, Any]:
    """Move a draft back by one version without touching Google Forms."""
    return _draft_service().undo(draft_id)


@mcp.tool()
def publish_form_draft(
    draft_id: str,
    expected_version: int | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Create a native Google Form from the exact approved draft version."""
    if not confirm:
        return _draft_service().publish(draft_id, confirm=False, expected_version=expected_version)
    return _draft_service(with_google=True).publish(
        draft_id, confirm=True, expected_version=expected_version
    )


@mcp.tool()
def update_existing_google_form(
    form_id: str,
    operations: list[PatchOperation] | None = None,
    plan_token: str | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Preview or apply a signed targeted update plan to an existing Google Form."""
    if not confirm:
        if not operations:
            return {
                "status": "invalid_request",
                "form_id": form_id,
                "message": "At least one patch operation is required.",
            }
        revision_id = _google_gateway().get_form_revision(form_id)
        operation_data = [operation.model_dump(exclude_none=True) for operation in operations]
        signed_plan = _confirmation_signer().sign(
            {
                "form_id": form_id,
                "revision_id": revision_id,
                "operations": operation_data,
            }
        )
        return {
            "status": "confirmation_required",
            "form_id": form_id,
            "revision_id": revision_id,
            "operations": operation_data,
            "plan_token": signed_plan,
            "message": (
                "Review these exact operations, then call again with confirm=true "
                "and this plan_token."
            ),
        }
    if not plan_token:
        return {
            "status": "confirmation_plan_required",
            "form_id": form_id,
            "message": "Pass the signed plan token returned by the reviewed update plan.",
        }
    try:
        plan = _confirmation_signer().verify(plan_token)
        if plan.get("form_id") != form_id:
            raise InvalidConfirmationPlan("Confirmation plan is for a different form")
        planned_operations = _PATCH_OPERATIONS_ADAPTER.validate_python(plan.get("operations"))
        revision_id = str(plan["revision_id"])
    except (InvalidConfirmationPlan, KeyError, ValueError) as exc:
        return {
            "status": "invalid_confirmation_plan",
            "form_id": form_id,
            "message": str(exc),
        }
    return _google_gateway().patch_form(
        form_id,
        planned_operations,
        expected_revision_id=revision_id,
    )


@mcp.tool()
def google_forms_auth_status() -> dict[str, Any]:
    """Report OAuth file locations and whether authorization is configured."""
    return authorization_status()


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
