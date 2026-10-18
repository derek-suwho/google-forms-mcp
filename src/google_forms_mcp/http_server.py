from __future__ import annotations

import hmac
import os

import uvicorn
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from google_forms_mcp.server import mcp


class BearerAuthApp:
    """Protect an ASGI app with a fixed bearer token."""

    def __init__(self, app: ASGIApp, token: str) -> None:
        self._app = app
        self._token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        if scope.get("path") == "/health":
            response = JSONResponse({"status": "ok", "transport": "streamable-http"})
            await response(scope, receive, send)
            return

        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        supplied = headers.get("authorization", "")
        expected = f"Bearer {self._token}"
        if not hmac.compare_digest(supplied, expected):
            response = JSONResponse(
                {"error": "unauthorized"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return

        await self._app(scope, receive, send)


def build_http_app(
    token: str,
    *,
    host: str = "127.0.0.1",
    public_hosts: list[str] | None = None,
) -> ASGIApp:
    if not token:
        raise ValueError("A non-empty connector bearer token is required.")
    allowed_hosts = [
        "127.0.0.1",
        "127.0.0.1:*",
        "localhost",
        "localhost:*",
        "testserver",
        *(public_hosts or []),
    ]
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed_hosts,
        allowed_origins=["https://chatgpt.com", "https://claude.ai"],
    )
    app = mcp.streamable_http_app(
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        host=host,
        transport_security=security,
    )
    return BearerAuthApp(app, token)


def main() -> None:
    token = os.environ.get("GOOGLE_FORMS_CONNECTOR_TOKEN", "")
    if len(token) < 32:
        raise SystemExit(
            "GOOGLE_FORMS_CONNECTOR_TOKEN must be set to a random value of at least 32 characters."
        )

    host = os.environ.get("GOOGLE_FORMS_CONNECTOR_HOST", "0.0.0.0")
    public_hosts = [
        value.strip()
        for value in os.environ.get("GOOGLE_FORMS_CONNECTOR_PUBLIC_HOSTS", "").split(",")
        if value.strip()
    ]
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(
        build_http_app(token, host=host, public_hosts=public_hosts),
        host=host,
        port=port,
    )


if __name__ == "__main__":
    main()
