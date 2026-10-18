from __future__ import annotations

from pathlib import Path

import pytest

from google_forms_mcp.confirmation import ConfirmationSigner, InvalidConfirmationPlan


def test_confirmation_plan_round_trip_and_private_key_permissions(tmp_path: Path) -> None:
    key_path = tmp_path / "confirmation.key"
    signer = ConfirmationSigner(key_path)
    payload = {
        "form_id": "form-1",
        "revision_id": "rev-1",
        "operations": [{"operation": "set_form_title", "new_title": "Approved"}],
    }

    token = signer.sign(payload)

    assert signer.verify(token) == payload
    assert key_path.stat().st_mode & 0o777 == 0o600


def test_confirmation_plan_rejects_tampering(tmp_path: Path) -> None:
    signer = ConfirmationSigner(tmp_path / "confirmation.key")
    token = signer.sign({"form_id": "form-1", "operations": []})
    payload, signature = token.split(".", 1)
    tampered = ("A" if payload[0] != "A" else "B") + payload[1:] + "." + signature

    with pytest.raises(InvalidConfirmationPlan):
        signer.verify(tampered)
