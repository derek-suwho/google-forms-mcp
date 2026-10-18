from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import cast

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from google_forms_mcp.multiuser import MultiUserStore
from google_forms_mcp.tenant import require_user_id


def multiuser_enabled() -> bool:
    return os.environ.get("GOOGLE_FORMS_MULTIUSER", "").lower() in {
        "1",
        "true",
        "yes",
    }


def multiuser_data_dir() -> Path:
    configured = os.environ.get("GOOGLE_FORMS_MULTIUSER_DATA_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".config" / "google-forms-mcp" / "multiuser"


@lru_cache(maxsize=4)
def _cached_store(database: str, key: str) -> MultiUserStore:
    return MultiUserStore(database, key)


def multiuser_store() -> MultiUserStore:
    root = multiuser_data_dir()
    database = os.environ.get("GOOGLE_FORMS_USERS_DB", str(root / "users.db"))
    key = os.environ.get("GOOGLE_FORMS_MASTER_KEY", str(root / "master.key"))
    return _cached_store(database, key)


def tenant_credentials() -> Credentials:
    user_id = require_user_id()
    store = multiuser_store()
    serialized = store.get_google_credentials(user_id)
    if not serialized:
        raise PermissionError("This account is not connected to Google")
    credentials = cast(
        Credentials,
        Credentials.from_authorized_user_info(  # type: ignore[no-untyped-call]
            json.loads(serialized)
        ),
    )
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())  # type: ignore[no-untyped-call]
        store.set_google_credentials(
            user_id,
            credentials.to_json(),  # type: ignore[no-untyped-call]
        )
    if not credentials.valid:
        raise PermissionError("Google authorization is invalid or expired")
    return credentials


def tenant_runtime_dir() -> Path:
    user_id = require_user_id()
    root = multiuser_data_dir() / "tenants" / user_id
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        root.chmod(0o700)
    except OSError:
        pass
    return root
