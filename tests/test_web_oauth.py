from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from google_forms_mcp.multiuser import MultiUserStore
from google_forms_mcp.web_oauth import GoogleWebOAuth, GoogleWebOAuthNotConfigured


def test_web_oauth_rejects_missing_and_desktop_client_files(tmp_path: Path) -> None:
    store = MultiUserStore(tmp_path / "users.db", tmp_path / "master.key")

    with pytest.raises(GoogleWebOAuthNotConfigured):
        GoogleWebOAuth(store, "", "https://forms.example.com")

    desktop = tmp_path / "desktop.json"
    desktop.write_text('{"installed":{"client_id":"desktop"}}')
    with pytest.raises(GoogleWebOAuthNotConfigured, match="Web application"):
        GoogleWebOAuth(store, desktop, "https://forms.example.com")


def test_web_oauth_can_be_built_from_secret_environment_values(tmp_path: Path) -> None:
    store = MultiUserStore(tmp_path / "users.db", tmp_path / "master.key")

    oauth = GoogleWebOAuth.from_client_values(
        store,
        client_id="client.apps.googleusercontent.com",
        client_secret="secret-value",
        project_id="project-id",
        public_base_url="https://forms.example.com",
    )

    assert oauth.redirect_uri == "https://forms.example.com/oauth/google/callback"
    query = parse_qs(urlparse(oauth.authorization_url(binding="browser-binding")).query)
    assert query.get("include_granted_scopes", ["false"])[0] != "true"
    assert query["scope"][0].split() == [
        "openid",
        "email",
        "https://www.googleapis.com/auth/forms.body",
    ]
