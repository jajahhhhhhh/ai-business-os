"""Interim auth model (TD-5): apikey vs proxy modes of require_principal."""

from __future__ import annotations

import pytest
from starlette.requests import Request

from src.config import Settings
from src.interfaces.dependencies import require_principal
from src.interfaces.problems import ProblemError


def make_request(authorization: str | None = None) -> Request:
    headers = []
    if authorization is not None:
        headers.append((b"authorization", authorization.encode()))
    return Request({"type": "http", "method": "GET", "path": "/v1/x", "headers": headers})


class NoKeySession:
    """Session whose api-key lookup finds nothing."""

    async def execute(self, stmt):  # noqa: ANN001, ANN201 - test double
        class Result:
            @staticmethod
            def scalar_one_or_none():
                return None

        return Result()


def settings(**overrides) -> Settings:
    return Settings(env="prod", database_url="postgresql+asyncpg://x:x@localhost/x", **overrides)


async def test_dev_mode_bypasses_auth() -> None:
    principal = await require_principal(make_request(), Settings(env="dev"), NoKeySession())
    assert principal.actor == "dev"


async def test_prod_apikey_mode_rejects_keyless_requests() -> None:
    with pytest.raises(ProblemError) as exc:
        await require_principal(make_request(), settings(auth_mode="apikey"), NoKeySession())
    assert exc.value.status == 401


async def test_prod_proxy_mode_trusts_keyless_request_as_owner() -> None:
    principal = await require_principal(make_request(), settings(auth_mode="proxy"), NoKeySession())
    assert principal.actor == "owner"
    assert principal.scopes == ("*",)


async def test_prod_proxy_mode_still_validates_presented_bearer_keys() -> None:
    # A wrong key must NOT silently fall back to owner trust.
    with pytest.raises(ProblemError) as exc:
        await require_principal(
            make_request("Bearer wrong-key"), settings(auth_mode="proxy"), NoKeySession()
        )
    assert exc.value.status == 401


async def test_malformed_scheme_in_proxy_mode_is_treated_as_keyless() -> None:
    # "Basic ..." reaches the API when Caddy basic_auth fronts it — the
    # proxy already authenticated the owner; absence of a Bearer key is fine.
    principal = await require_principal(
        make_request("Basic abc123"), settings(auth_mode="proxy"), NoKeySession()
    )
    assert principal.actor == "owner"
