"""QA agent deterministic rubric (pure, orchestrator-free).

Score 0-100 per report: Thai content present, required sections per kind,
length bounds. The LLM rubric (qa agent, budget-permitting) is blended 50/50
with this score for sampled analytics reports; when the LLM is unavailable
the deterministic score stands alone.
"""

from __future__ import annotations

import re

THAI_RE = re.compile(r"[\u0e00-\u0e7f]")  # Thai Unicode block

RUBRIC_REPORT_QUALITY = "report-quality"
RUBRIC_RUN_HEALTH = "run-health"

# Required plain-text section markers per report kind.
REQUIRED_SECTIONS: dict[str, tuple[str, ...]] = {
    "daily": ("สรุปประจำวัน", "สิ่งสำคัญที่สุด"),
    "weekly": ("รายงานคู่แข่งประจำสัปดาห์",),
    "planning": ("แผนสัปดาห์",),
}

# (min_chars, max_chars) per kind; outside -> length deduction.
LENGTH_BOUNDS: dict[str, tuple[int, int]] = {
    "daily": (40, 4_000),
    "weekly": (40, 8_000),
    "planning": (40, 4_000),
}
DEFAULT_BOUNDS = (40, 8_000)

THAI_POINTS = 30
SECTIONS_POINTS = 40
LENGTH_POINTS = 30


def score_report(kind: str, body: str | None) -> tuple[int, str]:
    """Deterministic (score, notes). Empty/missing body scores 0."""
    if not body or not body.strip():
        return 0, "ไม่มีเนื้อหารายงาน"

    failures: list[str] = []
    score = 100

    if not THAI_RE.search(body):
        score -= THAI_POINTS
        failures.append("ไม่พบข้อความภาษาไทย")

    sections = REQUIRED_SECTIONS.get(kind, ())
    if sections:
        missing = [section for section in sections if section not in body]
        if missing:
            score -= round(SECTIONS_POINTS * len(missing) / len(sections))
            failures.append(f"ขาดหัวข้อ: {', '.join(missing)}")

    low, high = LENGTH_BOUNDS.get(kind, DEFAULT_BOUNDS)
    if not low <= len(body) <= high:
        score -= LENGTH_POINTS
        failures.append(f"ความยาว {len(body)} ตัวอักษร อยู่นอกช่วง {low}-{high}")

    score = max(0, min(100, score))
    notes = "; ".join(failures) if failures else "ผ่านเกณฑ์ทุกข้อ"
    return score, notes


def score_run_health(status: str) -> tuple[int, str]:
    """Rubric for sampled runs that produced no report: did the run succeed?"""
    if status == "succeeded":
        return 100, "รันสำเร็จ (ไม่มีรายงานให้ตรวจ)"
    return 0, f"สถานะรัน: {status}"


def blend_scores(deterministic: int, llm_score: int) -> int:
    """50/50 blend, clamped to 0-100 (documented in the qa agent docstring)."""
    blended = round((deterministic + llm_score) / 2)
    return max(0, min(100, blended))


def parse_llm_score(text: str) -> tuple[int, str] | None:
    """Parse '{"score": N, "notes": "..."}' defensively; None when unusable."""
    import json

    candidate = text.strip()
    if not candidate.startswith("{"):
        start, end = candidate.find("{"), candidate.rfind("}")
        if start == -1 or end <= start:
            return None
        candidate = candidate[start : end + 1]
    try:
        data = json.loads(candidate)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        score = int(data.get("score"))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    notes = str(data.get("notes", "")).strip()
    return max(0, min(100, score)), notes


# Inline fallback for packages/prompts/qa/evaluate.th.j2.
# Required template variables: kind, body.
EVALUATE_PROMPT_FALLBACK_TH = (
    "คุณเป็นผู้ตรวจคุณภาพรายงานภาษาไทยของระบบเอเจนต์อัตโนมัติ\n"
    'รายงานชนิด "{{ kind }}" ด้านล่างนี้ ให้คะแนนคุณภาพ 0-100\n'
    "(ความครบถ้วน ความถูกต้องของโครงสร้าง ความอ่านง่ายใน LINE):\n\n"
    "{{ body }}\n\n"
    "ตอบเป็น JSON เท่านั้น ห้ามมีข้อความอื่นนอก JSON โครงสร้าง:\n"
    '{"score": 0-100, "notes": "เหตุผลสั้น ๆ ภาษาไทย"}'
)
