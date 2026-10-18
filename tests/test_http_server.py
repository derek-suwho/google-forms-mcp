from __future__ import annotations

from starlette.testclient import TestClient

from google_forms_mcp.http_server import build_http_app


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
    with TestClient(
        build_http_app("top-secret", public_hosts=["forms.example.com"])
    ) as client:
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
