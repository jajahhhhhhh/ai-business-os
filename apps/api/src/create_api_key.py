"""Mint a scoped API key: python -m src.create_api_key <name> [scopes] [days]

The raw key is printed ONCE and never stored (only its SHA-256 digest lands in
api_keys). Use for MCP servers (AIBOS_API_KEY), the smoke test, and curl.

Examples:
    python -m src.create_api_key mcp-knowledge-base
    python -m src.create_api_key smoke-test '*' 30
"""

from __future__ import annotations

import asyncio
import secrets
import sys
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa

from src.config import get_settings
from src.infrastructure.db import build_engine, build_sessionmaker
from src.infrastructure.models import ApiKey, User
from src.infrastructure.security import hash_api_key


async def create(name: str, scopes: list[str], expires_days: int | None) -> None:
    settings = get_settings()
    engine = build_engine(settings.database_url)
    try:
        maker = build_sessionmaker(engine)
        async with maker() as session:
            existing = (
                await session.execute(sa.select(ApiKey).where(ApiKey.name == name))
            ).scalar_one_or_none()
            if existing is not None:
                sys.exit(f"api key named {name!r} already exists — pick another name")

            owner = (
                (await session.execute(sa.select(User).where(User.role == "owner")))
                .scalars()
                .first()
            )
            if owner is None:
                sys.exit("no owner user found — run `python -m src.seed` first")

            raw = secrets.token_urlsafe(32)
            session.add(
                ApiKey(
                    user_id=owner.id,
                    name=name,
                    hash=hash_api_key(raw),
                    scopes=scopes,
                    expires_at=(
                        datetime.now(UTC) + timedelta(days=expires_days) if expires_days else None
                    ),
                )
            )
            await session.commit()
            print(f"name:    {name}")
            print(f"scopes:  {scopes}")
            print(f"expires: {expires_days or 'never'} (days)")
            print(f"key:     {raw}")
            print("Store it now — it cannot be recovered, only replaced.")
    finally:
        await engine.dispose()


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    name = sys.argv[1]
    scopes = sys.argv[2].split(",") if len(sys.argv) > 2 else ["*"]
    expires_days = int(sys.argv[3]) if len(sys.argv) > 3 else None
    asyncio.run(create(name, scopes, expires_days))


if __name__ == "__main__":
    main()
