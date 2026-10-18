from pathlib import Path

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
