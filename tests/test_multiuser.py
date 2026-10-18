from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from google_forms_mcp.multiuser import InvalidUserToken, MultiUserStore


def test_user_credentials_are_encrypted_and_tokens_are_hashed(tmp_path: Path) -> None:
    database = tmp_path / "users.db"
    store = MultiUserStore(database, tmp_path / "master.key")
    credentials = '{"refresh_token":"secret-refresh","scopes":["forms.body"]}'

    user = store.upsert_google_user("google-sub-1", "person@example.com", credentials)
    plaintext_token = store.create_api_token(user.user_id, label="Claude")

    assert store.authenticate_api_token(plaintext_token).user_id == user.user_id
    assert store.get_google_credentials(user.user_id) == credentials
    raw = database.read_bytes()
    assert b"secret-refresh" not in raw
    assert plaintext_token.encode() not in raw
    assert b"secret-refresh" not in json.dumps(store.list_audit_events(user.user_id)).encode()
    assert database.stat().st_mode & 0o777 == 0o600
    assert (tmp_path / "master.key").stat().st_mode & 0o777 == 0o600


def test_token_revocation_and_google_disconnect_are_isolated_per_user(tmp_path: Path) -> None:
    store = MultiUserStore(tmp_path / "users.db", tmp_path / "master.key")
    first = store.upsert_google_user("sub-1", "first@example.com", '{"token":"one"}')
    second = store.upsert_google_user("sub-2", "second@example.com", '{"token":"two"}')
    first_token = store.create_api_token(first.user_id, label="ChatGPT")
    second_token = store.create_api_token(second.user_id, label="Claude")

    store.revoke_api_token(first.user_id, first_token)
    with pytest.raises(InvalidUserToken):
        store.authenticate_api_token(first_token)
    assert store.authenticate_api_token(second_token).user_id == second.user_id

    store.disconnect_google(first.user_id)
    assert store.get_google_credentials(first.user_id) is None
    assert store.get_google_credentials(second.user_id) == '{"token":"two"}'


def test_oauth_state_is_single_use_and_expires(tmp_path: Path) -> None:
    store = MultiUserStore(tmp_path / "users.db", tmp_path / "master.key")

    state = store.create_oauth_state("verifier-1", binding="browser-one", now=100, ttl_seconds=60)
    assert store.consume_oauth_state(state, binding="wrong-browser", now=119) is None
    assert store.consume_oauth_state(state, binding="browser-one", now=120) == "verifier-1"
    assert store.consume_oauth_state(state, binding="browser-one", now=121) is None

    expired = store.create_oauth_state("verifier-2", binding="browser-two", now=200, ttl_seconds=10)
    assert store.consume_oauth_state(expired, binding="browser-two", now=211) is None


def test_database_never_stores_raw_oauth_state(tmp_path: Path) -> None:
    database = tmp_path / "users.db"
    store = MultiUserStore(database, tmp_path / "master.key")
    state = store.create_oauth_state("verifier", binding="browser-secret", now=100, ttl_seconds=60)

    connection = sqlite3.connect(database)
    stored = connection.execute("SELECT state_hash FROM oauth_states").fetchone()[0]
    connection.close()

    assert state not in stored


def test_concurrent_oauth_state_consumption_succeeds_exactly_once(tmp_path: Path) -> None:
    store = MultiUserStore(tmp_path / "users.db", tmp_path / "master.key")
    state = store.create_oauth_state("verifier", binding="browser", now=100, ttl_seconds=60)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: store.consume_oauth_state(state, binding="browser", now=110),
                range(2),
            )
        )

    assert results.count("verifier") == 1
    assert results.count(None) == 1
