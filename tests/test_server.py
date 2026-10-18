import asyncio

from google_forms_mcp.models import FormSpec
from google_forms_mcp.server import create_google_form, mcp


def test_mcp_server_exposes_preview_create_and_auth_status_tools() -> None:
    tools = asyncio.run(mcp.list_tools())
    names = {tool.name for tool in tools}

    assert names == {
        "preview_google_form",
        "create_google_form",
        "google_forms_auth_status",
    }


def test_preview_tool_schema_requires_a_form_spec() -> None:
    tools = asyncio.run(mcp.list_tools())
    preview = next(tool for tool in tools if tool.name == "preview_google_form")

    assert "spec" in preview.input_schema["properties"]
    assert "spec" in preview.input_schema["required"]


def test_create_rejects_missing_confirmation_before_attempting_oauth() -> None:
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

    assert create_google_form(spec, confirm=False) == {
        "status": "confirmation_required",
        "message": "Review the preview and obtain explicit user approval before creating the form.",
    }
