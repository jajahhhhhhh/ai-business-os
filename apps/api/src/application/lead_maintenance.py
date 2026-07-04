"""Lead maintenance use cases (M5): weekly clustering + PDPA anonymization.

cluster_leads (Sun 05:30): greedy threshold clustering (cosine >= 0.85) over
fresh embeddings of active leads' name + discovered excerpt. Skips cleanly
when the embedder is unavailable (the `ml` extra is optional, NFR-1). Greedy
single-pass clustering was chosen over §8.1's HDBSCAN for the current lead
volume — tracked in docs/tech-debt.md, revisit past ~500 active leads.

anonymize_stale_leads (Sun 05:45, §8.5 PDPA): leads whose last activity
(fallback: first_seen_at) is older than 18 months and that were never won
lose their name and encrypted contact; the action is recorded as a lead
event and audited.
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import structlog

from src.application.ports import Embedder
from src.application.repositories import AuditWriter, LeadMaintenanceRepository

logger = structlog.get_logger("application.lead_maintenance")

CLUSTER_THRESHOLD = 0.85
STALE_MONTHS = 18
ANONYMIZED_NAME = "ไม่ระบุ (anonymized)"


# ------------------------------------------------------------ pure helpers


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def greedy_clusters(
    items: Sequence[tuple[Any, Sequence[float]]],
    threshold: float = CLUSTER_THRESHOLD,
) -> list[list[Any]]:
    """Single-pass greedy clustering: each item joins the first existing
    cluster whose representative (first member) is >= threshold similar,
    otherwise it founds a new cluster. Deterministic in input order."""
    representatives: list[Sequence[float]] = []
    clusters: list[list[Any]] = []
    for key, vector in items:
        for index, rep in enumerate(representatives):
            if _cosine(vector, rep) >= threshold:
                clusters[index].append(key)
                break
        else:
            representatives.append(vector)
            clusters.append([key])
    return clusters


def months_before(now: datetime, months: int) -> datetime:
    """Calendar-aware `months` back from `now`, clamping the day (Mar 31 - 1
    month -> Feb 28/29). Used for the 18-month PDPA retention cutoff."""
    total = (now.year * 12 + (now.month - 1)) - months
    year, month = divmod(total, 12)
    month += 1
    # Clamp the day to the target month's length.
    if month == 12:
        next_month_start = datetime(year + 1, 1, 1, tzinfo=UTC)
    else:
        next_month_start = datetime(year, month + 1, 1, tzinfo=UTC)
    last_day = (next_month_start - datetime(year, month, 1, tzinfo=UTC)).days
    return now.replace(year=year, month=month, day=min(now.day, last_day))


# ----------------------------------------------------------------- use cases


class LeadMaintenanceUseCases:
    def __init__(
        self,
        repo: LeadMaintenanceRepository,
        audit: AuditWriter,
        *,
        embedder: Embedder | None = None,
    ) -> None:
        self._repo = repo
        self._audit = audit
        self._embedder = embedder

    async def cluster_leads(self, actor: str) -> dict[str, Any]:
        """Assign leads.cluster_id per >=2-member greedy cluster."""
        if self._embedder is None or not self._embedder.is_available:
            logger.info("cluster_leads_skipped", reason="embedder unavailable")
            return {"status": "skipped", "reason": "embedder unavailable"}
        rows = await self._repo.leads_for_clustering()
        if not rows:
            return {"status": "done", "leads": 0, "clusters": 0, "clustered": 0}
        vectors = await self._embedder.embed_texts([text for _, text in rows])
        groups = greedy_clusters(
            [(lead_id, vector) for (lead_id, _), vector in zip(rows, vectors, strict=True)]
        )
        mapping: dict[uuid.UUID, uuid.UUID] = {}
        clusters = 0
        for group in groups:
            if len(group) < 2:
                continue  # singletons keep their existing cluster_id (usually NULL)
            clusters += 1
            cluster_id = uuid.uuid4()
            for lead_id in group:
                mapping[lead_id] = cluster_id
        await self._repo.set_cluster_ids(mapping)
        result = {
            "status": "done",
            "leads": len(rows),
            "clusters": clusters,
            "clustered": len(mapping),
        }
        await self._audit.write(actor, "leads.clustered", "leads", None, result)
        logger.info("cluster_leads_done", **{k: v for k, v in result.items() if k != "status"})
        return result

    async def anonymize_stale_leads(
        self, actor: str, now: datetime | None = None
    ) -> dict[str, Any]:
        """§8.5: 18 months of inactivity (and not won) -> anonymize."""
        now = now or datetime.now(UTC)
        cutoff = months_before(now, STALE_MONTHS)
        stale = await self._repo.stale_leads(cutoff, exclude_name=ANONYMIZED_NAME)
        for lead in stale:
            await self._repo.anonymize_lead(lead.id, ANONYMIZED_NAME)
            await self._repo.add_lead_event(
                lead.id,
                "anonymized",
                {"reason": "pdpa_retention", "cutoff": cutoff.isoformat()},
                now,
            )
            await self._audit.write(
                actor,
                "lead.anonymized",
                "leads",
                lead.id,
                {"cutoff": cutoff.isoformat()},
            )
        result = {"status": "done", "anonymized": len(stale), "cutoff": cutoff.isoformat()}
        logger.info("anonymize_stale_leads_done", anonymized=len(stale))
        return result
