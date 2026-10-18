from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from starlette.testclient import TestClient

from google_forms_mcp.http_server import build_http_app, build_multiuser_http_app
from google_forms_mcp.multiuser import MultiUserStore


class FakeWebOAuth:
    def __init__(self) -> None:
        self.binding: str | None = None

    def authorization_url(self, *, binding: str) -> str:
        self.binding = binding
        return "https://accounts.example.test/authorize"


def test_health_endpoint_is_public_and_does_not_expose_secrets() -> None:
    with TestClient(build_http_app("top-secret")) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "transport": "streamable-http"}
    assert "top-secret" not in response.text


def test_mcp_endpoint_rejects_missing_or_wrong_bearer_token() -> None:
    with TestClient(build_http_app("top-secret")) as client:
        missing = client.post("/mcp")
        wrong = client.post("/mcp", headers={"Authorization": "Bearer wrong"})

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert missing.headers["www-authenticate"] == "Bearer"


def test_mcp_endpoint_accepts_matching_bearer_before_protocol_validation() -> None:
    with TestClient(build_http_app("top-secret")) as client:
        response = client.post(
            "/mcp",
            headers={
                "Authorization": "Bearer top-secret",
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
        )

    assert response.status_code == 200


def test_public_host_allowlist_blocks_dns_rebinding() -> None:
    with TestClient(build_http_app("top-secret", public_hosts=["forms.example.com"])) as client:
        allowed = client.post(
            "/mcp",
            headers={
                "Host": "forms.example.com",
                "Authorization": "Bearer top-secret",
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
        )
        blocked = client.post(
            "/mcp",
            headers={
                "Host": "evil.example.com",
                "Authorization": "Bearer top-secret",
                "Content-Type": "application/json",
            },
            json={"jsonrpc": "2.0", "id": 2, "method": "ping"},
        )

    assert allowed.status_code == 200
    assert blocked.status_code == 421


def test_multiuser_account_endpoint_requires_and_resolves_user_token(
    tmp_path: Path,
) -> None:
    store = MultiUserStore(tmp_path / "users.db", tmp_path / "master.key")
    user = store.upsert_google_user("sub-1", "user@example.com", '{"token":"x"}')
    token = store.create_api_token(user.user_id, label="Test")

    with TestClient(
        build_multiuser_http_app(store=store, oauth=None, public_hosts=["testserver"])
    ) as client:
        denied = client.get("/account")
        allowed = client.get("/account", headers={"Authorization": f"Bearer {token}"})

    assert denied.status_code == 401
    assert allowed.status_code == 200
    assert allowed.json() == {
        "user_id": user.user_id,
        "email": "user@example.com",
        "google_connected": True,
    }


def test_multiuser_landing_is_public_and_missing_web_oauth_fails_closed(
    tmp_path: Path,
) -> None:
    store = MultiUserStore(tmp_path / "users.db", tmp_path / "master.key")

    with TestClient(build_multiuser_http_app(store=store, oauth=None)) as client:
        landing = client.get("/")
        connect = client.get("/connect/google")

    assert landing.status_code == 200
    assert "Connect Google Forms" in landing.text
    assert connect.status_code == 503


def test_multiuser_rate_limit_is_per_user_across_tokens(tmp_path: Path) -> None:
    store = MultiUserStore(tmp_path / "users.db", tmp_path / "master.key")
    first = store.upsert_google_user("sub-1", "one@example.com", '{"token":"1"}')
    second = store.upsert_google_user("sub-2", "two@example.com", '{"token":"2"}')
    first_token = store.create_api_token(first.user_id, label="One")
    first_alternate_token = store.create_api_token(first.user_id, label="One alternate")
    second_token = store.create_api_token(second.user_id, label="Two")

    with TestClient(
        build_multiuser_http_app(
            store=store,
            oauth=None,
            rate_limit_per_minute=1,
        )
    ) as client:
        first_ok = client.get("/account", headers={"Authorization": f"Bearer {first_token}"})
        first_limited = client.get(
            "/account",
            headers={"Authorization": f"Bearer {first_alternate_token}"},
        )
        second_ok = client.get("/account", headers={"Authorization": f"Bearer {second_token}"})

    assert first_ok.status_code == 200
    assert first_limited.status_code == 429
    assert second_ok.status_code == 200


def test_google_onboarding_is_browser_bound_and_publicly_rate_limited(
    tmp_path: Path,
) -> None:
    store = MultiUserStore(tmp_path / "users.db", tmp_path / "master.key")
    oauth = FakeWebOAuth()

    with TestClient(
        build_multiuser_http_app(
            store=store,
            oauth=cast(Any, oauth),
            public_rate_limit_per_minute=1,
        )
    ) as client:
        first = client.get("/connect/google", follow_redirects=False)
        limited = client.get(
            "/connect/google",
            headers={"CF-Connecting-IP": "203.0.113.99"},
            follow_redirects=False,
        )

    assert first.status_code == 302
    assert oauth.binding
    cookie = first.headers["set-cookie"]
    assert "gfm_oauth_binding=" in cookie
    assert "HttpOnly" in cookie
    assert "Secure" in cookie
    assert "SameSite=lax" in cookie
    assert limited.status_code == 429


def test_public_global_limit_survives_many_proxy_client_ips(tmp_path: Path) -> None:
    store = MultiUserStore(tmp_path / "users.db", tmp_path / "master.key")
    oauth = FakeWebOAuth()

    with TestClient(
        build_multiuser_http_app(
            store=store,
            oauth=cast(Any, oauth),
            public_rate_limit_per_minute=100,
            public_global_rate_limit_per_minute=2,
            trust_proxy_headers=True,
        )
    ) as client:
        statuses = [
            client.get(
                "/connect/google",
                headers={"CF-Connecting-IP": f"203.0.113.{index}"},
                follow_redirects=False,
            ).status_code
            for index in range(1, 4)
        ]

    assert statuses == [302, 302, 429]
