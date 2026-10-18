from __future__ import annotations

from typing import Any

from google_forms_mcp.compiler import compile_create_body, compile_item_requests
from google_forms_mcp.models import FormSpec


class GoogleFormsGateway:
    """Thin adapter around the generated Google Forms API client."""

    def __init__(self, google_service: Any) -> None:
        self._google = google_service

    def create_form(self, spec: FormSpec) -> dict[str, Any]:
        resource = self._google.forms()
        created = resource.create(body=compile_create_body(spec)).execute()
        form_id = str(created["formId"])

        requests: list[dict[str, Any]] = []
        if spec.description:
            requests.append(
                {
                    "updateFormInfo": {
                        "info": {"description": spec.description},
                        "updateMask": "description",
                    }
                }
            )
        requests.extend(compile_item_requests(spec))

        resource.batchUpdate(
            formId=form_id,
            body={"includeFormInResponse": True, "requests": requests},
        ).execute()

        return {
            "formId": form_id,
            "editUri": f"https://docs.google.com/forms/d/{form_id}/edit",
            "responderUri": created["responderUri"],
        }
