from __future__ import annotations

import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/forms.body"]
ACCEPTED_SCOPES = {
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/forms.body",
}


def has_supported_scope(scopes: Sequence[str] | None) -> bool:
    return bool(ACCEPTED_SCOPES.intersection(scopes or []))


def credential_paths() -> tuple[Path, Path]:
    config_home = Path(
        os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
    ).expanduser()
    app_dir = config_home / "google-forms-mcp"
    client = Path(
        os.environ.get("GOOGLE_FORMS_CLIENT_SECRET", str(app_dir / "credentials.json"))
    ).expanduser()
    token = Path(os.environ.get("GOOGLE_FORMS_TOKEN", str(app_dir / "token.json"))).expanduser()
    return client, token


def load_credentials() -> Credentials:
    client_path, token_path = credential_paths()
    credentials: Credentials | None = None

    if token_path.exists():
        loaded = Credentials.from_authorized_user_file(  # type: ignore[no-untyped-call]
            str(token_path)
        )
        if has_supported_scope(loaded.scopes):
            credentials = loaded

    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())  # type: ignore[no-untyped-call]
    elif not credentials or not credentials.valid:
        if not client_path.exists():
            raise FileNotFoundError(
                f"Google OAuth client file not found at {client_path}. "
                "Download a Desktop app OAuth client from Google Cloud, place it there, "
                "then run google-forms-auth."
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(client_path), SCOPES)
        credentials = flow.run_local_server(port=0)

    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(credentials.to_json(), encoding="utf-8")
    try:
        token_path.chmod(0o600)
    except OSError:
        pass
    return credentials


def authorization_status() -> dict[str, Any]:
    client_path, token_path = credential_paths()
    return {
        "client_secret_path": str(client_path),
        "client_secret_exists": client_path.exists(),
        "token_path": str(token_path),
        "token_exists": token_path.exists(),
        "scopes": SCOPES,
    }


def main() -> None:
    credentials = load_credentials()
    print(
        json.dumps(
            {
                "status": "authorized",
                "valid": credentials.valid,
                "scopes": SCOPES,
            },
            indent=2,
        )
    )
