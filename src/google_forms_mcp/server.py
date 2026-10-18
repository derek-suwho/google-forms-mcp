from __future__ import annotations

from typing import Any

from googleapiclient.discovery import build
from mcp.server.mcpserver import MCPServer

from google_forms_mcp.auth import authorization_status, load_credentials
from google_forms_mcp.google_gateway import GoogleFormsGateway
from google_forms_mcp.models import FormSpec
from google_forms_mcp.service import FormService

mcp = MCPServer(
    name="google-forms",
    instructions=(
        "Preview every form before creation. Only call create_google_form with confirm=true "
        "after the user has reviewed and explicitly approved the draft."
    ),
)


class _PreviewOnlyGateway:
    def create_form(self, spec: FormSpec) -> dict[str, Any]:
        raise RuntimeError("The preview tool never creates forms.")


def _creation_service() -> FormService:
    credentials = load_credentials()
    google = build("forms", "v1", credentials=credentials, cache_discovery=False)
    return FormService(GoogleFormsGateway(google))


@mcp.tool()
def preview_google_form(spec: FormSpec) -> dict[str, Any]:
    """Validate and preview a Google Form without creating anything."""
    return FormService(_PreviewOnlyGateway()).preview(
        spec.model_dump(exclude_computed_fields=True)
    )


@mcp.tool()
def create_google_form(spec: FormSpec, confirm: bool = False) -> dict[str, Any]:
    """Create a native Google Form after explicit user confirmation."""
    if not confirm:
        return {
            "status": "confirmation_required",
            "message": "Review the preview and obtain explicit user approval before creating the form.",
        }
    return _creation_service().create(
        spec.model_dump(exclude_computed_fields=True), confirm=confirm
    )


@mcp.tool()
def google_forms_auth_status() -> dict[str, Any]:
    """Report OAuth file locations and whether authorization is configured."""
    return authorization_status()


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
