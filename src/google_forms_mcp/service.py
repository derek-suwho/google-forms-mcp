from __future__ import annotations

from typing import Any, Protocol

from google_forms_mcp.models import FormSpec


class ConfirmationRequired(ValueError):
    """Raised when a mutating operation lacks explicit user confirmation."""


class FormsGateway(Protocol):
    def create_form(self, spec: FormSpec) -> dict[str, Any]: ...


class FormService:
    """Validation and safety boundary shared by every transport adapter."""

    def __init__(self, gateway: FormsGateway) -> None:
        self._gateway = gateway

    def preview(self, raw_spec: dict[str, Any]) -> dict[str, Any]:
        spec = FormSpec.model_validate(raw_spec)
        return {
            "status": "draft",
            "summary": {
                "title": spec.title,
                "sections": len(spec.sections),
                "questions": spec.question_count,
            },
            "spec": spec.model_dump(exclude_computed_fields=True),
            "next_step": "Review this draft, then call create_google_form with confirm=true.",
        }

    def create(self, raw_spec: dict[str, Any], *, confirm: bool) -> dict[str, Any]:
        if not confirm:
            raise ConfirmationRequired(
                "Creating a Google Form is a side effect; review a preview and pass confirm=true."
            )

        spec = FormSpec.model_validate(raw_spec)
        created = self._gateway.create_form(spec)
        return {
            "status": "created",
            "form_id": created["formId"],
            "edit_url": created["editUri"],
            "responder_url": created["responderUri"],
            "summary": {
                "title": spec.title,
                "sections": len(spec.sections),
                "questions": spec.question_count,
            },
        }
