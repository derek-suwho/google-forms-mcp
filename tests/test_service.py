from __future__ import annotations

from typing import Any

import pytest

from google_forms_mcp.models import FormSpec
from google_forms_mcp.service import ConfirmationRequired, FormService


class RecordingGateway:
    def __init__(self) -> None:
        self.received: list[FormSpec] = []

    def create_form(self, spec: FormSpec) -> dict[str, Any]:
        self.received.append(spec)
        return {
            "formId": "abc123",
            "responderUri": "https://docs.google.com/forms/d/e/abc123/viewform",
            "editUri": "https://docs.google.com/forms/d/abc123/edit",
        }


def raw_spec() -> dict[str, Any]:
    return {
        "title": "Event RSVP",
        "description": "Join us",
        "sections": [
            {
                "title": "Details",
                "questions": [
                    {"title": "Name", "type": "short_text", "required": True},
                    {
                        "title": "Attending?",
                        "type": "multiple_choice",
                        "options": ["Yes", "No"],
                    },
                ],
            }
        ],
    }


def test_preview_returns_normalized_spec_without_creating_a_form() -> None:
    gateway = RecordingGateway()
    service = FormService(gateway)

    preview = service.preview(raw_spec())

    assert preview["status"] == "draft"
    assert preview["summary"] == {"title": "Event RSVP", "sections": 1, "questions": 2}
    assert preview["spec"]["sections"][0]["questions"][0]["required"] is True
    assert gateway.received == []


def test_create_requires_explicit_confirmation() -> None:
    service = FormService(RecordingGateway())

    with pytest.raises(ConfirmationRequired, match="confirm=true"):
        service.create(raw_spec(), confirm=False)


def test_create_returns_native_google_form_links_after_confirmation() -> None:
    gateway = RecordingGateway()
    service = FormService(gateway)

    result = service.create(raw_spec(), confirm=True)

    assert result["status"] == "created"
    assert result["form_id"] == "abc123"
    assert result["edit_url"].endswith("/abc123/edit")
    assert result["responder_url"].endswith("/abc123/viewform")
    assert len(gateway.received) == 1
