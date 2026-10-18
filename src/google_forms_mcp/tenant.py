from __future__ import annotations

from contextvars import ContextVar, Token

_current_user_id: ContextVar[str | None] = ContextVar(
    "google_forms_mcp_current_user_id", default=None
)


class TenantRequired(PermissionError):
    """Raised when a multi-user operation has no authenticated tenant."""


def current_user_id() -> str | None:
    return _current_user_id.get()


def require_user_id() -> str:
    user_id = current_user_id()
    if not user_id:
        raise TenantRequired("An authenticated user is required")
    return user_id


def set_current_user(user_id: str) -> Token[str | None]:
    return _current_user_id.set(user_id)


def reset_current_user(token: Token[str | None]) -> None:
    _current_user_id.reset(token)
