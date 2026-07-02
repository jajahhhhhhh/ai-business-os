"""FastAPI dependencies: settings, DB session, and the API-key auth seam."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

import sqlalchemy as sa
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import Settings
from src.infrastructure.models import ApiKey
from src.infrastructure.security import hash_api_key
from src.interfaces.problems import ProblemError


@dataclass(frozen=True, slots=True)
class Principal:
    """The authenticated caller, used as the audit-log actor."""

    actor: str
    scopes: tuple[str, ...]


def get_app_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """One session per request; commit on success, rollback on any error."""
    maker = request.app.state.sessionmaker
    async with maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


SettingsDep = Annotated[Settings, Depends(get_app_settings)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _unauthorized(detail: str) -> ProblemError:
    return ProblemError(
        status=401,
        title="Unauthorized",
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def require_principal(
    request: Request, settings: SettingsDep, session: SessionDep
) -> Principal:
    """Bearer API-key auth against the api_keys table; bypassed when ENV=dev.

    TODO(M1): Auth.js session -> JWT verification plugs in here; this
    dependency is the single seam the rest of the API depends on.
    """
    if settings.env == "dev":
        return Principal(actor="dev", scopes=("*",))

    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise _unauthorized("Missing bearer API key")

    stmt = sa.select(ApiKey).where(ApiKey.hash == hash_api_key(token.strip()))
    key = (await session.execute(stmt)).scalar_one_or_none()
    if key is None:
        raise _unauthorized("Unknown API key")
    if key.expires_at is not None and key.expires_at <= datetime.now(UTC):
        raise _unauthorized("API key expired")
    return Principal(actor=f"api-key:{key.name}", scopes=tuple(key.scopes or ()))


PrincipalDep = Annotated[Principal, Depends(require_principal)]
