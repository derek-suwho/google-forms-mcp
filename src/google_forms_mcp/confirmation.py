from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
from typing import Any


class InvalidConfirmationPlan(ValueError):
    """Raised when a signed mutation plan is missing, corrupt, or altered."""


class ConfirmationSigner:
    """Persist and use a private HMAC key for reviewed mutation plans."""

    def __init__(self, key_path: str | Path) -> None:
        self.key_path = Path(key_path).expanduser()

    def _key(self) -> bytes:
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.key_path.exists():
            key = os.urandom(32)
            try:
                descriptor = os.open(
                    self.key_path,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                )
            except FileExistsError:
                pass
            else:
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(key)
        try:
            self.key_path.chmod(0o600)
        except OSError:
            pass
        key = self.key_path.read_bytes()
        if len(key) < 32:
            raise InvalidConfirmationPlan("Confirmation key is invalid")
        return key

    @staticmethod
    def _encode(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")

    @staticmethod
    def _decode(value: str) -> bytes:
        padding = "=" * (-len(value) % 4)
        return base64.urlsafe_b64decode(value + padding)

    def sign(self, payload: dict[str, Any]) -> str:
        encoded_payload = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        signature = hmac.new(self._key(), encoded_payload, hashlib.sha256).digest()
        return f"{self._encode(encoded_payload)}.{self._encode(signature)}"

    def verify(self, token: str) -> dict[str, Any]:
        try:
            payload_part, signature_part = token.split(".", 1)
            payload = self._decode(payload_part)
            signature = self._decode(signature_part)
        except (ValueError, TypeError) as exc:
            raise InvalidConfirmationPlan("Confirmation plan is malformed") from exc
        expected = hmac.new(self._key(), payload, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            raise InvalidConfirmationPlan("Confirmation plan signature is invalid")
        try:
            parsed = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise InvalidConfirmationPlan("Confirmation plan payload is invalid") from exc
        if not isinstance(parsed, dict):
            raise InvalidConfirmationPlan("Confirmation plan payload must be an object")
        return parsed
