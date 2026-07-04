"""Idempotent seed: owner user, the two renovation sites, contractor MR.HOME.

Run once after migrations:  python -m src.seed
Safe to re-run — existing rows (matched by natural key) are left untouched.
"""

from __future__ import annotations

import asyncio

import sqlalchemy as sa

from src.config import get_settings
from src.infrastructure.db import build_engine, build_sessionmaker
from src.infrastructure.models import Contractor, Site, Source, User

OWNER_EMAIL = "ch_company@howtoniksen.com"
SITES = (
    ("Lipa Noi", "Lipa Noi, Koh Samui"),
    ("Chaweng", "Chaweng, Koh Samui"),
)
CONTRACTOR = "MR.HOME"

# Default M5 lead sources (§8.4: Reddit via official API only). Inert until
# REDDIT_CLIENT_ID/SECRET are configured — the collector then reports
# 'skipped: no credentials' instead of scraping.
LEAD_SOURCES = (
    ("r/kohsamui", "kohsamui", None),
    ("r/thailand samui", "thailand", "samui villa OR koh samui accommodation"),
    ("r/digitalnomad samui", "digitalnomad", "samui"),
)


async def seed() -> None:
    settings = get_settings()
    engine = build_engine(settings.database_url)
    try:
        maker = build_sessionmaker(engine)
        async with maker() as session:
            owner = (
                await session.execute(sa.select(User).where(User.email == OWNER_EMAIL))
            ).scalar_one_or_none()
            if owner is None:
                session.add(User(email=OWNER_EMAIL, name="Owner", role="owner", locale="th"))
                print(f"created user {OWNER_EMAIL} (role=owner, locale=th)")
            else:
                print(f"user {OWNER_EMAIL} already present")

            for name, location in SITES:
                site = (
                    await session.execute(sa.select(Site).where(Site.name == name))
                ).scalar_one_or_none()
                if site is None:
                    session.add(Site(name=name, location=location))
                    print(f"created site {name}")
                else:
                    print(f"site {name} already present")

            contractor = (
                await session.execute(sa.select(Contractor).where(Contractor.name == CONTRACTOR))
            ).scalar_one_or_none()
            if contractor is None:
                session.add(Contractor(name=CONTRACTOR))
                print(f"created contractor {CONTRACTOR}")
            else:
                print(f"contractor {CONTRACTOR} already present")

            for name, subreddit, query in LEAD_SOURCES:
                source = (
                    await session.execute(sa.select(Source).where(Source.name == name))
                ).scalar_one_or_none()
                if source is None:
                    session.add(
                        Source(
                            name=name,
                            type="reddit",
                            url=f"https://www.reddit.com/r/{subreddit}/",
                            config_json={"subreddit": subreddit, "query": query},
                            tos_policy="allowed",
                            rate_limit_per_hr=12,
                            enabled=True,
                        )
                    )
                    print(f"created lead source {name}")
                else:
                    print(f"lead source {name} already present")

            await session.commit()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
