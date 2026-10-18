from __future__ import annotations

import json
import secrets
import urllib.request
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlencode

from google_auth_oauthlib.flow import Flow

from google_forms_mcp.multiuser import MultiUserStore, UserRecord

GOOGLE_SCOPES = [
    "openid",
    "email",
    "https://www.googleapis.com/auth/forms.body",
]


class GoogleWebOAuthNotConfigured(RuntimeError):
    """Raised when a Web application OAuth client is unavailable."""


class GoogleWebOAuth:
    def __init__(
        self,
        store: MultiUserStore,
        client_secret_path: str | Path,
        public_base_url: str,
    ) -> None:
        self.store = store
        self.client_secret_path = Path(client_secret_path).expanduser()
        self.public_base_url = public_base_url.rstrip("/")
        self._validate_client()

    @property
    def redirect_uri(self) -> str:
        return f"{self.public_base_url}/oauth/google/callback"

    def _client_config(self) -> dict[str, Any]:
        if not self.client_secret_path.is_file():
            raise GoogleWebOAuthNotConfigured(
                f"Google Web OAuth client file not found: {self.client_secret_path}"
            )
        try:
            parsed = json.loads(self.client_secret_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise GoogleWebOAuthNotConfigured("Google OAuth client JSON cannot be read") from exc
        if not isinstance(parsed, dict):
            raise GoogleWebOAuthNotConfigured("Google OAuth client JSON is invalid")
        config = cast(dict[str, Any], parsed)
        if "web" not in config:
            raise GoogleWebOAuthNotConfigured(
                "Google OAuth client must have application type Web application"
            )
        return config

    def _validate_client(self) -> None:
        self._client_config()

    def authorization_url(self, *, binding: str) -> str:
        verifier = secrets.token_urlsafe(64)
        state = self.store.create_oauth_state(verifier, binding=binding)
        flow = Flow.from_client_config(
            self._client_config(),
            scopes=GOOGLE_SCOPES,
            state=state,
            code_verifier=verifier,
            autogenerate_code_verifier=False,
        )
        flow.redirect_uri = self.redirect_uri
        url, _ = flow.authorization_url(
            access_type="offline",
            prompt="consent",
            include_granted_scopes="true",
        )
        return str(url)

    @staticmethod
    def _fetch_user_info(access_token: str) -> dict[str, Any]:
        request = urllib.request.Request(
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            parsed = json.loads(response.read().decode("utf-8"))
        if not isinstance(parsed, dict):
            raise TypeError("Google userinfo response is invalid")
        return cast(dict[str, Any], parsed)

    @staticmethod
    def revoke_serialized_credentials(credentials_json: str) -> bool:
        data = json.loads(credentials_json)
        token = data.get("refresh_token") or data.get("token")
        if not token:
            return False
        body = urlencode({"token": str(token)}).encode("utf-8")
        request = urllib.request.Request(
            "https://oauth2.googleapis.com/revoke",
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data=body,
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                status = int(response.status)
                return 200 <= status < 300
        except OSError:
            return False

    def complete(self, *, state: str, code: str, binding: str) -> tuple[UserRecord, str]:
        verifier = self.store.consume_oauth_state(state, binding=binding)
        if not verifier:
            raise ValueError("OAuth state is invalid, expired, or already used")
        flow = Flow.from_client_config(
            self._client_config(),
            scopes=GOOGLE_SCOPES,
            state=state,
            code_verifier=verifier,
            autogenerate_code_verifier=False,
        )
        flow.redirect_uri = self.redirect_uri
        flow.fetch_token(code=code)
        credentials = flow.credentials
        user_info = self._fetch_user_info(credentials.token)
        subject = str(user_info.get("sub", ""))
        email = str(user_info.get("email", ""))
        if not subject or not email:
            raise ValueError("Google did not return a stable subject and email")
        user = self.store.upsert_google_user(subject, email, credentials.to_json())
        token = self.store.create_api_token(user.user_id, label="Initial MCP token")
        return user, token
