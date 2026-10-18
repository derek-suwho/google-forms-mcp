from __future__ import annotations

import hashlib
import hmac
import html
import os
import secrets
import time
from http.cookies import SimpleCookie
from urllib.parse import parse_qs

import anyio
import uvicorn
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from google_forms_mcp.multitenancy import multiuser_enabled, multiuser_store
from google_forms_mcp.multiuser import InvalidUserToken, MultiUserStore
from google_forms_mcp.server import mcp
from google_forms_mcp.tenant import reset_current_user, set_current_user
from google_forms_mcp.web_oauth import GoogleWebOAuth, GoogleWebOAuthNotConfigured


def _headers(scope: Scope) -> dict[str, str]:
    return {
        key.decode("latin-1").lower(): value.decode("latin-1")
        for key, value in scope.get("headers", [])
    }


def _bearer(scope: Scope) -> str | None:
    authorization = _headers(scope).get("authorization", "")
    if not authorization.startswith("Bearer "):
        return None
    token = authorization[7:].strip()
    return token or None


def _cookie(scope: Scope, name: str) -> str | None:
    cookie = SimpleCookie()
    cookie.load(_headers(scope).get("cookie", ""))
    morsel = cookie.get(name)
    return morsel.value if morsel else None


def _client_ip(scope: Scope, *, trust_proxy_headers: bool = False) -> str:
    headers = _headers(scope)
    if trust_proxy_headers and headers.get("cf-connecting-ip"):
        return headers["cf-connecting-ip"].strip()
    client = scope.get("client")
    return str(client[0]) if client else "unknown"


def _mcp_app(*, host: str, public_hosts: list[str] | None = None) -> ASGIApp:
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
    return mcp.streamable_http_app(
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        host=host,
        transport_security=security,
    )


class BearerAuthApp:
    """Protect an ASGI app with one fixed personal bearer token."""

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
        supplied = _headers(scope).get("authorization", "")
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


class MultiUserAuthApp:
    """Google onboarding and per-user bearer authentication for MCP."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        store: MultiUserStore,
        oauth: GoogleWebOAuth | None,
        rate_limit_per_minute: int = 60,
        public_rate_limit_per_minute: int = 10,
        public_global_rate_limit_per_minute: int = 120,
        trust_proxy_headers: bool = False,
    ) -> None:
        self._app = app
        self._store = store
        self._oauth = oauth
        self._rate_limit = max(1, rate_limit_per_minute)
        self._rate_windows: dict[str, tuple[float, int]] = {}
        self._public_rate_limit = max(1, public_rate_limit_per_minute)
        self._public_global_rate_limit = max(1, public_global_rate_limit_per_minute)
        self._trust_proxy_headers = trust_proxy_headers
        self._public_rate_windows: dict[str, tuple[float, int]] = {}
        self._public_global_window: tuple[float, int] = (time.monotonic(), 0)

    def _rate_allowed(self, user_id: str) -> bool:
        key = hashlib.sha256(user_id.encode("utf-8")).hexdigest()
        now = time.monotonic()
        started, count = self._rate_windows.get(key, (now, 0))
        if now - started >= 60:
            started, count = now, 0
        if count >= self._rate_limit:
            self._rate_windows[key] = (started, count)
            return False
        self._rate_windows[key] = (started, count + 1)
        return True

    def _public_rate_allowed(self, scope: Scope) -> bool:
        now = time.monotonic()
        global_started, global_count = self._public_global_window
        if now - global_started >= 60:
            global_started, global_count = now, 0
        if global_count >= self._public_global_rate_limit:
            self._public_global_window = (global_started, global_count)
            return False
        self._public_global_window = (global_started, global_count + 1)

        self._public_rate_windows = {
            key: value for key, value in self._public_rate_windows.items() if now - value[0] < 60
        }
        client_ip = _client_ip(scope, trust_proxy_headers=self._trust_proxy_headers)
        key = hashlib.sha256(client_ip.encode("utf-8")).hexdigest()
        started, count = self._public_rate_windows.get(key, (now, 0))
        if now - started >= 60:
            started, count = now, 0
        if count >= self._public_rate_limit:
            self._public_rate_windows[key] = (started, count)
            return False
        self._public_rate_windows[key] = (started, count + 1)
        return True

    async def _respond_public(self, scope: Scope, receive: Receive, send: Send) -> bool:
        path = str(scope.get("path", ""))
        method = str(scope.get("method", "GET"))
        if path in {"/connect/google", "/oauth/google/callback"} and not self._public_rate_allowed(
            scope
        ):
            await JSONResponse(
                {"error": "rate_limit_exceeded"},
                status_code=429,
                headers={"Retry-After": "60"},
            )(scope, receive, send)
            return True
        if path == "/health":
            await JSONResponse(
                {
                    "status": "ok",
                    "transport": "streamable-http",
                    "mode": "multiuser",
                }
            )(scope, receive, send)
            return True
        if path == "/" and method == "GET":
            await HTMLResponse(
                """<!doctype html><html><head><title>Google Forms MCP</title></head>
                <body><main><h1>Google Forms MCP</h1>
                <p>Connect your own Google account, then use the issued private token in any MCP-compatible AI app.</p>
                <p><a href='/connect/google'>Connect Google Forms</a></p>
                <p>Your Google credentials are encrypted at rest. Tokens are shown once and can be revoked by disconnecting.</p>
                <p><a href='/privacy'>Privacy</a> · <a href='/terms'>Terms</a></p>
                </main></body></html>"""
            )(scope, receive, send)
            return True
        if path == "/privacy" and method == "GET":
            await HTMLResponse(
                """<!doctype html><html><head><title>Privacy</title></head><body><main>
                <h1>Privacy</h1><p>We store your email, encrypted Google authorization, hashed MCP tokens, form drafts, and minimal security audit events.</p>
                <p>We do not read or store Google Form responses. Audit logs exclude prompts, question text, and credentials.</p>
                <p>Disconnecting revokes service tokens and deletes the locally stored Google credential.</p>
                </main></body></html>"""
            )(scope, receive, send)
            return True
        if path == "/terms" and method == "GET":
            await HTMLResponse(
                """<!doctype html><html><head><title>Terms</title></head><body><main>
                <h1>Terms</h1><p>This is beta software. Review every proposed form mutation before approval.</p>
                <p>Do not use the service to collect unlawful, deceptive, or unauthorized sensitive information.</p>
                <p>You remain responsible for forms created in your Google account and for respondent access settings.</p>
                </main></body></html>"""
            )(scope, receive, send)
            return True
        if path == "/connect/google" and method == "GET":
            if self._oauth is None:
                await JSONResponse(
                    {"error": "Google Web OAuth is not configured"}, status_code=503
                )(scope, receive, send)
            else:
                new_binding = secrets.token_urlsafe(32)
                redirect_response = RedirectResponse(
                    self._oauth.authorization_url(binding=new_binding), status_code=302
                )
                redirect_response.set_cookie(
                    "gfm_oauth_binding",
                    new_binding,
                    max_age=600,
                    httponly=True,
                    secure=True,
                    samesite="lax",
                    path="/oauth/google/callback",
                )
                await redirect_response(scope, receive, send)
            return True
        if path == "/oauth/google/callback" and method == "GET":
            if self._oauth is None:
                await JSONResponse(
                    {"error": "Google Web OAuth is not configured"}, status_code=503
                )(scope, receive, send)
                return True
            oauth = self._oauth
            query = parse_qs(scope.get("query_string", b"").decode("utf-8"))
            if query.get("error"):
                await JSONResponse({"error": query["error"][0]}, status_code=400)(
                    scope, receive, send
                )
                return True
            state = query.get("state", [""])[0]
            code = query.get("code", [""])[0]
            browser_binding = _cookie(scope, "gfm_oauth_binding")
            if not state or not code or not browser_binding:
                missing_response = JSONResponse(
                    {"error": "Missing OAuth state, code, or browser binding"},
                    status_code=400,
                    headers={"Cache-Control": "no-store"},
                )
                missing_response.delete_cookie("gfm_oauth_binding", path="/oauth/google/callback")
                await missing_response(scope, receive, send)
                return True
            try:
                user, token = await anyio.to_thread.run_sync(
                    lambda: oauth.complete(state=state, code=code, binding=browser_binding)
                )
            except Exception:  # noqa: BLE001 - provider/network failures must become OAuth errors
                oauth_error_response = JSONResponse(
                    {"error": "Google authorization failed"},
                    status_code=400,
                    headers={"Cache-Control": "no-store"},
                )
                oauth_error_response.delete_cookie(
                    "gfm_oauth_binding", path="/oauth/google/callback"
                )
                await oauth_error_response(scope, receive, send)
                return True
            safe_email = html.escape(user.email)
            safe_token = html.escape(token)
            success_response = HTMLResponse(
                f"""<!doctype html><html><head><title>Connected</title></head>
                <body><main><h1>Google account connected</h1>
                <p>{safe_email}</p><p>Copy this token now. It will not be shown again.</p>
                <pre>{safe_token}</pre>
                <p>MCP endpoint: <code>/mcp</code></p></main></body></html>""",
                headers={
                    "Cache-Control": "no-store",
                    "Referrer-Policy": "no-referrer",
                    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
                },
            )
            success_response.delete_cookie("gfm_oauth_binding", path="/oauth/google/callback")
            await success_response(scope, receive, send)
            return True
        return False

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        if await self._respond_public(scope, receive, send):
            return
        raw_token = _bearer(scope)
        if not raw_token:
            await JSONResponse(
                {"error": "unauthorized"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )(scope, receive, send)
            return
        try:
            user = self._store.authenticate_api_token(raw_token)
        except InvalidUserToken:
            await JSONResponse(
                {"error": "unauthorized"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )(scope, receive, send)
            return
        if not self._rate_allowed(user.user_id):
            await JSONResponse(
                {"error": "rate_limit_exceeded"},
                status_code=429,
                headers={"Retry-After": "60"},
            )(scope, receive, send)
            return

        context_token = set_current_user(user.user_id)
        try:
            path = str(scope.get("path", ""))
            method = str(scope.get("method", "GET"))
            if path == "/account" and method == "GET":
                await JSONResponse(
                    {
                        "user_id": user.user_id,
                        "email": user.email,
                        "google_connected": user.google_connected,
                    }
                )(scope, receive, send)
                return
            if path == "/disconnect" and method == "POST":
                credentials = self._store.get_google_credentials(user.user_id)
                provider_revoked = False
                if credentials:
                    provider_revoked = GoogleWebOAuth.revoke_serialized_credentials(credentials)
                self._store.disconnect_google(user.user_id)
                await JSONResponse(
                    {
                        "status": "disconnected",
                        "provider_revoked": provider_revoked,
                    }
                )(scope, receive, send)
                return
            await self._app(scope, receive, send)
        finally:
            reset_current_user(context_token)


def build_http_app(
    token: str,
    *,
    host: str = "127.0.0.1",
    public_hosts: list[str] | None = None,
) -> ASGIApp:
    if not token:
        raise ValueError("A non-empty connector bearer token is required.")
    return BearerAuthApp(_mcp_app(host=host, public_hosts=public_hosts), token)


def build_multiuser_http_app(
    *,
    store: MultiUserStore,
    oauth: GoogleWebOAuth | None,
    host: str = "127.0.0.1",
    public_hosts: list[str] | None = None,
    rate_limit_per_minute: int = 60,
    public_rate_limit_per_minute: int = 10,
    public_global_rate_limit_per_minute: int = 120,
    trust_proxy_headers: bool = False,
) -> ASGIApp:
    return MultiUserAuthApp(
        _mcp_app(host=host, public_hosts=public_hosts),
        store=store,
        oauth=oauth,
        rate_limit_per_minute=rate_limit_per_minute,
        public_rate_limit_per_minute=public_rate_limit_per_minute,
        public_global_rate_limit_per_minute=public_global_rate_limit_per_minute,
        trust_proxy_headers=trust_proxy_headers,
    )


def main() -> None:
    host = os.environ.get("GOOGLE_FORMS_CONNECTOR_HOST", "0.0.0.0")
    public_hosts = [
        value.strip()
        for value in os.environ.get("GOOGLE_FORMS_CONNECTOR_PUBLIC_HOSTS", "").split(",")
        if value.strip()
    ]
    port = int(os.environ.get("PORT", "8000"))

    if multiuser_enabled():
        public_base_url = os.environ.get("GOOGLE_FORMS_PUBLIC_BASE_URL", "").rstrip("/")
        oauth: GoogleWebOAuth | None = None
        if public_base_url:
            try:
                oauth = GoogleWebOAuth(
                    multiuser_store(),
                    os.environ.get("GOOGLE_FORMS_WEB_CLIENT_SECRET", ""),
                    public_base_url,
                )
            except GoogleWebOAuthNotConfigured:
                oauth = None
        app = build_multiuser_http_app(
            store=multiuser_store(),
            oauth=oauth,
            host=host,
            public_hosts=public_hosts,
            rate_limit_per_minute=int(os.environ.get("GOOGLE_FORMS_RATE_LIMIT_PER_MINUTE", "60")),
            public_rate_limit_per_minute=int(
                os.environ.get("GOOGLE_FORMS_PUBLIC_RATE_LIMIT_PER_MINUTE", "10")
            ),
            public_global_rate_limit_per_minute=int(
                os.environ.get("GOOGLE_FORMS_PUBLIC_GLOBAL_RATE_LIMIT_PER_MINUTE", "120")
            ),
            trust_proxy_headers=os.environ.get("GOOGLE_FORMS_TRUST_PROXY_HEADERS", "").lower()
            in {"1", "true", "yes"},
        )
    else:
        token = os.environ.get("GOOGLE_FORMS_CONNECTOR_TOKEN", "")
        if len(token) < 32:
            raise SystemExit(
                "GOOGLE_FORMS_CONNECTOR_TOKEN must be set to a random value of at least 32 characters."
            )
        app = build_http_app(token, host=host, public_hosts=public_hosts)

    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
