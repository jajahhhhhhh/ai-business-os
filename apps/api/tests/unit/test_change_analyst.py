"""AnthropicChangeAnalyst: defensive JSON parsing, budget guard, agent_runs
bookkeeping, and the never-raise upgrade contract. HTTP is stubbed — no
network, no SDK."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from src.infrastructure.change_analyst import (
    ANTHROPIC_VERSION,
    AnthropicChangeAnalyst,
    NullChangeAnalyst,
    compute_cost_usd,
    parse_classification,
)
from tests.fakes import FakeRunRecorder

MODEL = "claude-haiku-4-5-20251001"
BUDGET = Decimal("5.00")


class StubResponse:
    def __init__(self, payload: dict[str, Any] | None = None, status_code: int = 200) -> None:
        self._payload = payload or {}
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict[str, Any]:
        return self._payload


class StubClient:
    """Queue of responses/exceptions; records every request for asserting."""

    def __init__(self, *results: StubResponse | Exception) -> None:
        self.results = list(results)
        self.requests: list[dict[str, Any]] = []

    async def post(self, url: str, *, headers: dict, json: dict) -> StubResponse:
        self.requests.append({"url": url, "headers": headers, "json": json})
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def _payload(text: str, tokens_in: int = 1000, tokens_out: int = 200) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": text}],
        "usage": {"input_tokens": tokens_in, "output_tokens": tokens_out},
    }


def _analyst(client: StubClient, recorder: FakeRunRecorder | None = None) -> AnthropicChangeAnalyst:
    return AnthropicChangeAnalyst(
        api_key="sk-test",
        model=MODEL,
        daily_budget_usd=BUDGET,
        recorder=recorder or FakeRunRecorder(),
        client=client,
    )


VALID_JSON = '{"category": "pricing", "severity": "high", "summary": "ลดราคาต่ำกว่าเรา"}'


# ----------------------------------------------------------------- parsing


def test_parse_plain_json() -> None:
    parsed = parse_classification(VALID_JSON)
    assert parsed is not None
    assert (parsed.category, parsed.severity, parsed.summary) == (
        "pricing",
        "high",
        "ลดราคาต่ำกว่าเรา",
    )


def test_parse_fenced_json_block() -> None:
    parsed = parse_classification(f"```json\n{VALID_JSON}\n```")
    assert parsed is not None and parsed.category == "pricing"


def test_parse_json_embedded_in_prose() -> None:
    parsed = parse_classification(f"นี่คือผลวิเคราะห์:\n{VALID_JSON}\nจบรายงาน")
    assert parsed is not None and parsed.severity == "high"


def test_parse_malformed_returns_none() -> None:
    assert parse_classification("ราคาเปลี่ยนแปลงมาก ไม่มี json") is None
    assert parse_classification('{"category": "pricing", ') is None
    assert parse_classification("") is None


def test_parse_unknown_enum_values_are_coerced() -> None:
    parsed = parse_classification('{"category": "weird", "severity": "urgent!!", "summary": "x"}')
    assert parsed is not None
    assert (parsed.category, parsed.severity) == ("other", "medium")


def test_parse_missing_summary_returns_none() -> None:
    assert parse_classification('{"category": "pricing", "severity": "low"}') is None


def test_parse_clips_summary_to_160_chars() -> None:
    parsed = parse_classification(
        '{"category": "content", "severity": "low", "summary": "' + "ก" * 500 + '"}'
    )
    assert parsed is not None and len(parsed.summary) == 160


# ----------------------------------------------------------------- pricing


def test_cost_is_1_in_5_out_per_million() -> None:
    assert compute_cost_usd(1_000_000, 1_000_000) == Decimal("6.0000")
    assert compute_cost_usd(1000, 200) == Decimal("0.0020")  # 0.001 + 0.001
    assert compute_cost_usd(0, 0) == Decimal("0.0000")


# ----------------------------------------------------------------- classify


async def test_classify_success_records_run_and_uses_spec_headers() -> None:
    recorder = FakeRunRecorder()
    client = StubClient(StubResponse(_payload(VALID_JSON)))
    analyst = _analyst(client, recorder)

    result = await analyst.classify("+ราคา 4,900", "Sunset Villa")

    assert result is not None and result.category == "pricing"
    [request] = client.requests
    assert request["headers"]["x-api-key"] == "sk-test"
    assert request["headers"]["anthropic-version"] == ANTHROPIC_VERSION == "2023-06-01"
    assert request["json"]["model"] == MODEL
    assert request["json"]["max_tokens"] == 600
    [row] = recorder.rows
    assert row["agent"] == "change-analyst"
    assert row["status"] == "succeeded"
    assert row["model"] == MODEL
    assert row["tokens_in"] == 1000 and row["tokens_out"] == 200
    assert row["cost_usd"] == Decimal("0.0020")


async def test_classify_unparseable_response_falls_back_to_none() -> None:
    recorder = FakeRunRecorder()
    analyst = _analyst(StubClient(StubResponse(_payload("ไม่ใช่ json"))), recorder)
    assert await analyst.classify("+diff", "V") is None
    assert len(recorder.rows) == 1  # the attempt is still on the books


async def test_classify_http_error_records_failed_run() -> None:
    recorder = FakeRunRecorder()
    analyst = _analyst(StubClient(StubResponse(status_code=529)), recorder)
    assert await analyst.classify("+diff", "V") is None
    [row] = recorder.rows
    assert row["status"] == "failed" and "529" in row["error"]


async def test_budget_guard_skips_call_and_records_fallback_row() -> None:
    recorder = FakeRunRecorder(today_cost=Decimal("5.00"))  # at the cap
    client = StubClient()  # any post() would IndexError -> proves no HTTP happened
    analyst = _analyst(client, recorder)

    assert await analyst.classify("+diff", "V") is None
    assert client.requests == []
    [row] = recorder.rows
    assert row["status"] == "skipped"
    assert row["model"] == "fallback"
    assert "budget" in row["error"]


async def test_under_budget_still_calls() -> None:
    recorder = FakeRunRecorder(today_cost=Decimal("4.99"))
    analyst = _analyst(StubClient(StubResponse(_payload(VALID_JSON))), recorder)
    assert await analyst.classify("+diff", "V") is not None


async def test_no_api_key_is_a_silent_fallback() -> None:
    recorder = FakeRunRecorder()
    analyst = AnthropicChangeAnalyst(
        api_key="", model=MODEL, daily_budget_usd=BUDGET, recorder=recorder, client=StubClient()
    )
    assert await analyst.classify("+diff", "V") is None
    assert await analyst.upgrade_weekly_report("draft") == "draft"
    assert recorder.rows == []  # no attempt was possible, nothing to record


# ------------------------------------------------------------------ upgrade


async def test_upgrade_returns_model_text_on_success() -> None:
    upgraded = "รายงาน...\n\nบทวิเคราะห์\n...\n\n3 สิ่งที่ควรทำ\n1) ..."
    analyst = _analyst(StubClient(StubResponse(_payload(upgraded))))
    assert await analyst.upgrade_weekly_report("draft") == upgraded


async def test_upgrade_falls_back_to_draft_on_any_failure() -> None:
    recorder = FakeRunRecorder()
    analyst = _analyst(StubClient(ConnectionError("api down")), recorder)
    assert await analyst.upgrade_weekly_report("ร่างรายงาน") == "ร่างรายงาน"
    [row] = recorder.rows
    assert row["status"] == "failed"


async def test_upgrade_over_budget_returns_draft() -> None:
    analyst = _analyst(StubClient(), FakeRunRecorder(today_cost=Decimal("99")))
    assert await analyst.upgrade_weekly_report("ร่าง") == "ร่าง"


async def test_null_analyst_always_falls_back() -> None:
    analyst = NullChangeAnalyst()
    assert await analyst.classify("+d", "V") is None
    assert await analyst.upgrade_weekly_report("ร่าง") == "ร่าง"
