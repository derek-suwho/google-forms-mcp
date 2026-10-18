from __future__ import annotations

from pathlib import Path

import pytest

from google_forms_mcp.auth import credential_paths, has_supported_scope


def test_drive_scope_is_accepted_for_google_forms_creation() -> None:
    assert has_supported_scope(["https://www.googleapis.com/auth/drive"])
    assert has_supported_scope(["https://www.googleapis.com/auth/drive.file"])
    assert has_supported_scope(["https://www.googleapis.com/auth/forms.body"])
    assert not has_supported_scope(["https://www.googleapis.com/auth/calendar"])


def test_credential_paths_honor_environment_overrides(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = tmp_path / "client.json"
    token = tmp_path / "token.json"
    monkeypatch.setenv("GOOGLE_FORMS_CLIENT_SECRET", str(client))
    monkeypatch.setenv("GOOGLE_FORMS_TOKEN", str(token))

    assert credential_paths() == (client, token)


def test_credential_paths_use_xdg_config_home(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("GOOGLE_FORMS_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("GOOGLE_FORMS_TOKEN", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    assert credential_paths() == (
        tmp_path / "google-forms-mcp" / "credentials.json",
        tmp_path / "google-forms-mcp" / "token.json",
    )
