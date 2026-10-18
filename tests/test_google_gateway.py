from __future__ import annotations

from typing import Any

from google_forms_mcp.google_gateway import GoogleFormsGateway
from google_forms_mcp.models import FormSpec


class Executable:
    def __init__(self, result: dict[str, Any]) -> None:
        self.result = result

    def execute(self) -> dict[str, Any]:
        return self.result


class FakeFormsResource:
    def __init__(self) -> None:
        self.create_bodies: list[dict[str, Any]] = []
        self.batch_calls: list[tuple[str, dict[str, Any]]] = []
        self.publish_calls: list[tuple[str, dict[str, Any]]] = []

    def create(self, *, body: dict[str, Any]) -> Executable:
        self.create_bodies.append(body)
        return Executable(
            {
                "formId": "form-42",
                "responderUri": "https://docs.google.com/forms/d/e/form-42/viewform",
            }
        )

    def batchUpdate(self, *, formId: str, body: dict[str, Any]) -> Executable:
        self.batch_calls.append((formId, body))
        return Executable({})

    def setPublishSettings(self, *, formId: str, body: dict[str, Any]) -> Executable:
        self.publish_calls.append((formId, body))
        return Executable({})


class FakeGoogleService:
    def __init__(self) -> None:
        self.resource = FakeFormsResource()

    def forms(self) -> FakeFormsResource:
        return self.resource


def test_gateway_creates_form_then_populates_it_in_one_batch() -> None:
    google = FakeGoogleService()
    gateway = GoogleFormsGateway(google)
    spec = FormSpec.model_validate(
        {
            "title": "Applicant intake",
            "description": "Complete every required field.",
            "sections": [
                {
                    "title": "Profile",
                    "questions": [{"title": "Name", "type": "short_text", "required": True}],
                }
            ],
        }
    )

    result = gateway.create_form(spec)

    assert google.resource.create_bodies == [
        {"info": {"title": "Applicant intake", "documentTitle": "Applicant intake"}}
    ]
    form_id, batch_body = google.resource.batch_calls[0]
    assert form_id == "form-42"
    assert batch_body["includeFormInResponse"] is True
    assert batch_body["requests"][0] == {
        "updateFormInfo": {
            "info": {"description": "Complete every required field."},
            "updateMask": "description",
        }
    }
    assert len(batch_body["requests"]) == 3
    assert google.resource.publish_calls == [
        (
            "form-42",
            {
                "publishSettings": {
                    "publishState": {
                        "isPublished": True,
                        "isAcceptingResponses": True,
                    }
                },
                "updateMask": "publishState",
            },
        )
    ]
    assert result == {
        "formId": "form-42",
        "editUri": "https://docs.google.com/forms/d/form-42/edit",
        "responderUri": "https://docs.google.com/forms/d/e/form-42/viewform",
    }
