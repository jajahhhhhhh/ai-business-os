"""End-to-end API flows against a real database."""

from __future__ import annotations

import os
import uuid

import pytest
from httpx import AsyncClient

DATABASE_URL = os.environ.get("DATABASE_URL", "")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL not set"),
]


async def test_health_liveness(client: AsyncClient) -> None:
    response = await client.get("/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["env"] == "dev"
    assert response.headers.get("x-request-id")


async def test_health_readiness_reports_database(client: AsyncClient) -> None:
    response = await client.get("/v1/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"]["database"]["status"] == "up"


async def test_metrics_exposition(client: AsyncClient) -> None:
    response = await client.get("/v1/metrics")
    assert response.status_code == 200
    assert "http_requests_total" in response.text


async def test_renovation_site_quotation_draw_pay_flow(client: AsyncClient) -> None:
    suffix = uuid.uuid4().hex[:8]

    site = (
        await client.post(
            "/v1/renovation/sites",
            json={"name": f"Lipa Noi {suffix}", "location": "Koh Samui", "budget_thb": "2000000"},
        )
    )
    assert site.status_code == 201, site.text
    site_id = site.json()["id"]

    contractor = await client.post(
        "/v1/renovation/contractors",
        json={"name": f"MR.HOME {suffix}", "line_id": "@mrhome"},
    )
    assert contractor.status_code == 201, contractor.text
    contractor_id = contractor.json()["id"]

    quotation = await client.post(
        "/v1/renovation/quotations",
        json={
            "site_id": site_id,
            "contractor_id": contractor_id,
            "category": "Electrical",
            "amount_thb": "100000",
        },
    )
    assert quotation.status_code == 201, quotation.text
    quotation_id = quotation.json()["id"]

    draw = await client.post(
        "/v1/renovation/draws",
        json={"quotation_id": quotation_id, "amount_thb": "40000"},
    )
    assert draw.status_code == 201, draw.text
    assert draw.json()["seq"] == 1
    draw_id = draw.json()["id"]

    paid = await client.post(f"/v1/renovation/draws/{draw_id}/pay")
    assert paid.status_code == 200, paid.text
    assert paid.json()["status"] == "paid"
    assert paid.json()["paid_at"] is not None

    # Paying twice violates draw immutability -> problem+json 409.
    double_pay = await client.post(f"/v1/renovation/draws/{draw_id}/pay")
    assert double_pay.status_code == 409
    assert double_pay.headers["content-type"].startswith("application/problem+json")

    # A draw beyond the remaining quotation amount is rejected.
    too_big = await client.post(
        "/v1/renovation/draws",
        json={"quotation_id": quotation_id, "amount_thb": "60000.01"},
    )
    assert too_big.status_code == 409
    assert too_big.headers["content-type"].startswith("application/problem+json")

    # A draw exactly at the remaining amount is fine and gets seq 2.
    exact = await client.post(
        "/v1/renovation/draws",
        json={"quotation_id": quotation_id, "amount_thb": "60000"},
    )
    assert exact.status_code == 201, exact.text
    assert exact.json()["seq"] == 2

    # Site summary reflects the paid vs pending split by category
    # (response shape mirrors apps/web/lib/types.ts SiteSummary).
    summary = await client.get(f"/v1/renovation/sites/{site_id}/summary")
    assert summary.status_code == 200, summary.text
    body = summary.json()
    electrical = next(c for c in body["spend_by_category"] if c["category"] == "Electrical")
    assert float(electrical["quoted_thb"]) == 100000.0
    assert float(electrical["spent_thb"]) == 40000.0
    assert float(body["spent_thb"]) == 40000.0
    assert float(body["outstanding_draws_thb"]) == 60000.0
    assert body["site"]["id"] == site_id
    assert sorted(d["seq"] for d in body["draws"]) == [1, 2]

    # The list endpoint carries the same per-site spend summary.
    sites = await client.get("/v1/renovation/sites")
    assert sites.status_code == 200
    listed = next(s for s in sites.json() if s["id"] == site_id)
    assert float(listed["spend_summary"]["spent_thb"]) == 40000.0
    assert float(listed["spend_summary"]["outstanding_thb"]) == 60000.0


async def test_lead_stage_transition_flow(client: AsyncClient, seeded_lead: uuid.UUID) -> None:
    listed = await client.get("/v1/leads", params={"stage": "discovered", "min_score": 60})
    assert listed.status_code == 200
    assert any(item["id"] == str(seeded_lead) for item in listed.json()["items"])

    moved = await client.post(f"/v1/leads/{seeded_lead}/stage", json={"stage": "qualified"})
    assert moved.status_code == 200, moved.text
    assert moved.json()["stage"] == "qualified"

    # Stage skipping is a domain violation -> problem+json 409.
    skipped = await client.post(f"/v1/leads/{seeded_lead}/stage", json={"stage": "won"})
    assert skipped.status_code == 409
    assert skipped.headers["content-type"].startswith("application/problem+json")

    # Unknown lead -> problem+json 404.
    missing = await client.post(f"/v1/leads/{uuid.uuid4()}/stage", json={"stage": "qualified"})
    assert missing.status_code == 404


async def test_lead_cursor_pagination(client: AsyncClient, app) -> None:  # type: ignore[no-untyped-def]
    from src.infrastructure.models import Lead

    marker = uuid.uuid4().hex[:12]
    async with app.state.sessionmaker() as session:
        for i in range(3):
            session.add(
                Lead(
                    kind="guest",
                    name=f"Page {marker} {i}",
                    intent_score=10,
                    stage="discovered",
                    dedup_hash=uuid.uuid4().hex,
                )
            )
        await session.commit()

    first = await client.get("/v1/leads", params={"q": marker, "limit": 2})
    assert first.status_code == 200
    page_one = first.json()
    assert len(page_one["items"]) == 2
    assert page_one["next_cursor"]

    second = await client.get(
        "/v1/leads", params={"q": marker, "limit": 2, "cursor": page_one["next_cursor"]}
    )
    assert second.status_code == 200
    page_two = second.json()
    assert len(page_two["items"]) == 1
    assert page_two["next_cursor"] is None

    ids_one = {item["id"] for item in page_one["items"]}
    ids_two = {item["id"] for item in page_two["items"]}
    assert not ids_one & ids_two

    # A tampered cursor is a 400 problem, not a 500.
    bad = await client.get("/v1/leads", params={"cursor": "garbage!!"})
    assert bad.status_code == 400
