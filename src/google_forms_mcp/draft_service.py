from __future__ import annotations

from typing import Any

from google_forms_mcp.drafts import DraftRecord, DraftStore
from google_forms_mcp.google_gateway import FormCreationError
from google_forms_mcp.models import FormSpec
from google_forms_mcp.patches import PatchOperation, apply_patches
from google_forms_mcp.service import FormsGateway


class PublishedDraftImmutable(RuntimeError):
    """Raised when a caller tries to edit a draft already linked to Google."""


class DraftService:
    """Persistent, patchable form drafts with explicit publication."""

    def __init__(self, store: DraftStore, gateway: FormsGateway) -> None:
        self._store = store
        self._gateway = gateway

    @staticmethod
    def _render(
        record: DraftRecord,
        *,
        changes: list[dict[str, object]] | None = None,
        status: str = "draft",
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "status": status,
            "draft_id": record.draft_id,
            "version": record.version,
            "published_form_id": record.published_form_id,
            "summary": {
                "title": record.spec.title,
                "sections": len(record.spec.sections),
                "questions": record.spec.question_count,
            },
            "spec": record.spec.model_dump(exclude_computed_fields=True),
        }
        if changes is not None:
            result["changes"] = changes
        return result

    def create(self, raw_spec: dict[str, Any]) -> dict[str, Any]:
        record = self._store.create(FormSpec.model_validate(raw_spec))
        return self._render(record)

    def get(self, draft_id: str) -> dict[str, Any]:
        record = self._store.get(draft_id)
        if record.published_form_id:
            if record.published_form_id.startswith("__publishing__:"):
                result = self._render(record, status="publishing")
                result["published_form_id"] = None
                return result
            if record.published_form_id.startswith("__failed__:"):
                _, _, form_id = record.published_form_id.split(":", 2)
                result = self._render(record, status="publication_failed")
                result["published_form_id"] = form_id
                result["edit_url"] = f"https://docs.google.com/forms/d/{form_id}/edit"
                return result
            return self._render(record, status="published")
        return self._render(record)

    def patch(self, draft_id: str, operations: list[PatchOperation]) -> dict[str, Any]:
        current = self._store.get(draft_id)
        if current.published_form_id:
            raise PublishedDraftImmutable(
                "Published drafts are immutable; use update_existing_google_form instead."
            )
        result = apply_patches(current.spec, operations)
        operation_data = [operation.model_dump(exclude_none=True) for operation in operations]
        updated = self._store.save_revision(
            draft_id,
            result.spec,
            changes=operation_data,
            expected_version=current.version,
        )
        return self._render(updated, changes=result.changes)

    def undo(self, draft_id: str) -> dict[str, Any]:
        current = self._store.get(draft_id)
        if current.published_form_id:
            raise PublishedDraftImmutable(
                "Published drafts are immutable; use update_existing_google_form instead."
            )
        return self._render(self._store.undo(draft_id), status="undone")

    def publish(
        self,
        draft_id: str,
        *,
        confirm: bool,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        current = self._store.get(draft_id)
        if not confirm:
            result = self._render(current, status="confirmation_required")
            result["message"] = (
                "Review this exact draft version, then publish with confirm=true "
                "and expected_version set to the reviewed version."
            )
            return result

        if expected_version is None:
            return {
                "status": "expected_version_required",
                "draft_id": draft_id,
                "current_version": current.version,
                "message": "Pass the exact draft version that the user reviewed.",
            }
        if current.version != expected_version:
            return {
                "status": "version_conflict",
                "draft_id": draft_id,
                "expected_version": expected_version,
                "current_version": current.version,
                "message": "The draft changed after review. Review the current version before publishing.",
            }

        if current.published_form_id:
            if current.published_form_id.startswith("__publishing__:"):
                return {
                    "status": "publishing",
                    "draft_id": draft_id,
                    "version": current.version,
                    "message": "This draft already has a publication in progress.",
                }
            if current.published_form_id.startswith("__failed__:"):
                _, _, form_id = current.published_form_id.split(":", 2)
                return {
                    "status": "publication_failed",
                    "draft_id": draft_id,
                    "form_id": form_id,
                    "edit_url": f"https://docs.google.com/forms/d/{form_id}/edit",
                    "message": "Google allocated this form, but setup did not finish. It will not be recreated automatically.",
                }
            return {
                "status": "already_published",
                "draft_id": draft_id,
                "form_id": current.published_form_id,
                "message": "This draft is already linked to a published Google Form.",
            }
        if not self._store.claim_publication(draft_id, expected_version=expected_version):
            latest = self._store.get(draft_id)
            if latest.published_form_id and latest.published_form_id.startswith("__publishing__:"):
                return {
                    "status": "publishing",
                    "draft_id": draft_id,
                    "version": latest.version,
                    "message": "This draft already has a publication in progress.",
                }
            if latest.published_form_id and latest.published_form_id.startswith("__failed__:"):
                _, _, form_id = latest.published_form_id.split(":", 2)
                return {
                    "status": "publication_failed",
                    "draft_id": draft_id,
                    "form_id": form_id,
                    "edit_url": f"https://docs.google.com/forms/d/{form_id}/edit",
                    "message": "Google allocated this form, but setup did not finish. It will not be recreated automatically.",
                }
            return {
                "status": "already_published",
                "draft_id": draft_id,
                "form_id": latest.published_form_id,
                "message": "This draft is already linked to a published Google Form.",
            }
        try:
            created = self._gateway.create_form(current.spec)
        except FormCreationError as exc:
            if exc.form_id:
                self._store.record_failed_publication(
                    draft_id,
                    exc.form_id,
                    expected_version=expected_version,
                )
            else:
                self._store.release_publication(draft_id, expected_version=expected_version)
            raise
        except Exception:
            self._store.release_publication(draft_id, expected_version=expected_version)
            raise
        try:
            marked = self._store.mark_published(
                draft_id,
                str(created["formId"]),
                expected_version=expected_version,
            )
        except Exception:
            self._store.record_failed_publication(
                draft_id,
                str(created["formId"]),
                expected_version=expected_version,
            )
            raise
        return {
            "status": "published",
            "draft_id": marked.draft_id,
            "version": marked.version,
            "form_id": created["formId"],
            "edit_url": created["editUri"],
            "responder_url": created["responderUri"],
            "summary": {
                "title": marked.spec.title,
                "sections": len(marked.spec.sections),
                "questions": marked.spec.question_count,
            },
        }
