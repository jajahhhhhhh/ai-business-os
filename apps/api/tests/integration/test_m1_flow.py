"""M1 flows against a real database: bank reconciliation + milestones."""

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


async def make_pending_draw(client: AsyncClient, amount: str) -> dict:
    """site → contractor → quotation → draw, returning the draw + context ids."""
    suffix = uuid.uuid4().hex[:8]
    site = (
        await client.post(
            "/v1/renovation/sites",
            json={"name": f"M1 Site {suffix}", "location": "Koh Samui", "budget_thb": "5000000"},
        )
    ).json()
    contractor = (
        await client.post("/v1/renovation/contractors", json={"name": f"MR.HOME {suffix}"})
    ).json()
    quotation = (
        await client.post(
            "/v1/renovation/quotations",
            json={
                "site_id": site["id"],
                "contractor_id": contractor["id"],
                "category": "Electrical",
                "amount_thb": amount,
            },
        )
    ).json()
    draw = (
        await client.post(
            "/v1/renovation/draws",
            json={"quotation_id": quotation["id"], "amount_thb": amount},
        )
    ).json()
    return {"site": site, "contractor": contractor, "quotation": quotation, "draw": draw}


async def test_ingest_match_confirm_pays_draw(client: AsyncClient) -> None:
    amount = "67890.25"  # unique-ish amount to avoid ambiguity with other test rows
    ctx = await make_pending_draw(client, amount)

    ingest = await client.post(
        "/v1/renovation/bank-alerts:ingest",
        json={
            "raw_text": (
                f"KBank เงินออกจากบัญชี X-1234 จำนวน 67,890.25 บาท "
                f"วันที่ 02/07/2569 09:00 ref-{uuid.uuid4().hex}"
            ),
            "source": "manual",
        },
    )
    assert ingest.status_code == 201
    tx = ingest.json()
    assert tx["status"] == "matched"
    assert tx["matched_draw_id"] == ctx["draw"]["id"]
    assert tx["ambiguous_match"] is False
    assert tx["amount_thb"] == pytest.approx(67890.25)

    confirm = await client.post(f"/v1/renovation/bank-transactions/{tx['id']}/confirm")
    assert confirm.status_code == 200
    assert confirm.json()["status"] == "confirmed"

    draws = (await client.get("/v1/renovation/draws", params={"site_id": ctx["site"]["id"]})).json()
    assert len(draws) == 1
    assert draws[0]["status"] == "paid"
    assert draws[0]["contractor_name"] == ctx["contractor"]["name"]

    # Confirming twice is a 409 problem, not a double payment.
    again = await client.post(f"/v1/renovation/bank-transactions/{tx['id']}/confirm")
    assert again.status_code == 409
    assert again.headers["content-type"].startswith("application/problem+json")


async def test_reingest_same_alert_dedups(client: AsyncClient) -> None:
    raw = (
        f"SCB รายการโอนเงินสำเร็จ จาก บัญชี xxx-x-x1111 จำนวนเงิน (THB) 123.45 "
        f"ref-{uuid.uuid4().hex}"
    )
    first = await client.post(
        "/v1/renovation/bank-alerts:ingest", json={"raw_text": raw, "source": "manual"}
    )
    assert first.status_code == 201
    second = await client.post(
        "/v1/renovation/bank-alerts:ingest", json={"raw_text": raw, "source": "manual"}
    )
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]


async def test_unparseable_text_is_422_problem(client: AsyncClient) -> None:
    response = await client.post(
        "/v1/renovation/bank-alerts:ingest",
        json={"raw_text": "สวัสดีครับ นัดดูหน้างานพรุ่งนี้", "source": "manual"},
    )
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert "not recognized" in response.json()["detail"]


async def test_manual_match_and_ignore(client: AsyncClient) -> None:
    ctx = await make_pending_draw(client, "55555.55")
    # Alert amount deliberately different -> unmatched.
    tx = (
        await client.post(
            "/v1/renovation/bank-alerts:ingest",
            json={
                "raw_text": (
                    f"BBL โอนเงินออกจากบัญชี ...9999 จำนวน 44,444.44 บาท " f"ref-{uuid.uuid4().hex}"
                ),
                "source": "manual",
            },
        )
    ).json()
    assert tx["status"] == "unmatched"

    matched = await client.post(
        f"/v1/renovation/bank-transactions/{tx['id']}/match",
        json={"draw_id": ctx["draw"]["id"]},
    )
    assert matched.status_code == 200
    assert matched.json()["matched_draw_id"] == ctx["draw"]["id"]

    ignored = await client.post(f"/v1/renovation/bank-transactions/{tx['id']}/ignore")
    assert ignored.status_code == 200
    assert ignored.json()["status"] == "ignored"


async def test_milestones_crud_and_summary_embed(client: AsyncClient) -> None:
    ctx = await make_pending_draw(client, "1000.00")
    site_id = ctx["site"]["id"]

    created = await client.post(
        f"/v1/renovation/sites/{site_id}/milestones",
        json={"name": "งานไฟฟ้าชั้น 2", "planned_date": "2026-07-15"},
    )
    assert created.status_code == 201
    milestone = created.json()
    assert milestone["status"] == "planned"

    advanced = await client.patch(
        f"/v1/renovation/milestones/{milestone['id']}", json={"status": "in_progress"}
    )
    assert advanced.status_code == 200
    assert advanced.json()["status"] == "in_progress"

    summary = (await client.get(f"/v1/renovation/sites/{site_id}/summary")).json()
    assert summary["site"]["id"] == site_id
    assert summary["outstanding_draws_thb"] == pytest.approx(1000.0)
    assert [m["id"] for m in summary["milestones"]] == [milestone["id"]]
    assert len(summary["draws"]) == 1
    assert summary["spend_by_category"][0]["category"] == "Electrical"


async def test_daily_snapshot_generates_thai_report(client: AsyncClient) -> None:
    response = await client.post("/v1/reports/daily-snapshot:generate")
    assert response.status_code == 201
    body = response.json()
    assert body["kind"] == "daily"
    assert body["lang"] == "th"
    assert body["body"].startswith("สรุปประจำวัน")
    assert body["line_sent"] is False  # no LINE credentials in tests

    listed = (await client.get("/v1/reports", params={"kind": "daily"})).json()
    assert any(r["id"] == body["id"] for r in listed)
    inline = next(r for r in listed if r["id"] == body["id"])
    assert inline["body"] == body["body"]
    assert inline["generated_at"]
