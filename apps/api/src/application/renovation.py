"""Phase A renovation use cases: sites, quotations, draws, payments."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from src.application.errors import NotFoundError
from src.application.repositories import (
    AuditWriter,
    ContractorRow,
    DrawRow,
    QuotationRow,
    RenovationRepository,
    SiteRow,
)
from src.domain.draws import (
    DrawLine,
    DrawStatus,
    next_seq,
    validate_new_draw,
    validate_payment,
)
from src.domain.money import Money


@dataclass(frozen=True, slots=True)
class CategorySpend:
    category: str
    quoted_thb: Decimal
    paid_thb: Decimal
    pending_thb: Decimal


@dataclass(frozen=True, slots=True)
class SiteSpendSummary:
    id: uuid.UUID
    name: str
    location: str | None
    budget_thb: Decimal | None
    categories: list[CategorySpend]
    total_quoted_thb: Decimal
    total_paid_thb: Decimal
    total_pending_thb: Decimal


def _summarize(site: SiteRow, categories: list[CategorySpend]) -> SiteSpendSummary:
    return SiteSpendSummary(
        id=site.id,
        name=site.name,
        location=site.location,
        budget_thb=site.budget_thb,
        categories=sorted(categories, key=lambda c: c.category),
        total_quoted_thb=sum((c.quoted_thb for c in categories), Decimal("0")),
        total_paid_thb=sum((c.paid_thb for c in categories), Decimal("0")),
        total_pending_thb=sum((c.pending_thb for c in categories), Decimal("0")),
    )


class RenovationUseCases:
    def __init__(self, repo: RenovationRepository, audit: AuditWriter) -> None:
        self._repo = repo
        self._audit = audit

    async def create_site(
        self, name: str, location: str | None, budget_thb: Decimal | None, actor: str
    ) -> SiteRow:
        site = await self._repo.create_site(name, location, budget_thb)
        await self._audit.write(actor, "site.created", "sites", site.id, {"name": name})
        return site

    async def create_contractor(
        self, name: str, contact: str | None, line_id: str | None, actor: str
    ) -> ContractorRow:
        contractor = await self._repo.create_contractor(name, contact, line_id)
        await self._audit.write(
            actor, "contractor.created", "contractors", contractor.id, {"name": name}
        )
        return contractor

    async def list_sites_with_spend(self) -> list[SiteSpendSummary]:
        sites = await self._repo.list_sites()
        by_site: dict[uuid.UUID, list[CategorySpend]] = {}
        for row in await self._repo.spend_rows():
            by_site.setdefault(row.site_id, []).append(
                CategorySpend(
                    category=row.category,
                    quoted_thb=row.quoted_thb,
                    paid_thb=row.paid_thb,
                    pending_thb=row.pending_thb,
                )
            )
        return [_summarize(site, by_site.get(site.id, [])) for site in sites]

    async def site_summary(self, site_id: uuid.UUID) -> SiteSpendSummary:
        site = await self._repo.get_site(site_id)
        if site is None:
            raise NotFoundError("site", site_id)
        categories = [
            CategorySpend(
                category=row.category,
                quoted_thb=row.quoted_thb,
                paid_thb=row.paid_thb,
                pending_thb=row.pending_thb,
            )
            for row in await self._repo.spend_rows()
            if row.site_id == site_id
        ]
        return _summarize(site, categories)

    async def create_quotation(
        self,
        site_id: uuid.UUID,
        contractor_id: uuid.UUID,
        category: str,
        amount_thb: Decimal,
        status: str,
        actor: str,
    ) -> QuotationRow:
        if await self._repo.get_site(site_id) is None:
            raise NotFoundError("site", site_id)
        if await self._repo.get_contractor(contractor_id) is None:
            raise NotFoundError("contractor", contractor_id)
        quotation = await self._repo.create_quotation(
            site_id, contractor_id, category, amount_thb, status
        )
        await self._audit.write(
            actor,
            "quotation.created",
            "quotations",
            quotation.id,
            {"category": category, "amount_thb": str(amount_thb)},
        )
        return quotation

    async def create_draw(
        self, quotation_id: uuid.UUID, amount_thb: Decimal, actor: str
    ) -> DrawRow:
        quotation = await self._repo.get_quotation(quotation_id)
        if quotation is None:
            raise NotFoundError("quotation", quotation_id)
        existing = [
            DrawLine(seq=d.seq, amount=Money(d.amount_thb), status=DrawStatus(d.status))
            for d in await self._repo.list_draws(quotation_id)
        ]
        validate_new_draw(Money(quotation.amount_thb), existing, Money(amount_thb))
        draw = await self._repo.create_draw(quotation_id, next_seq(existing), amount_thb)
        await self._audit.write(
            actor,
            "draw.created",
            "draws",
            draw.id,
            {"quotation_id": str(quotation_id), "seq": draw.seq, "amount_thb": str(amount_thb)},
        )
        return draw

    async def pay_draw(self, draw_id: uuid.UUID, actor: str) -> DrawRow:
        draw = await self._repo.get_draw(draw_id)
        if draw is None:
            raise NotFoundError("draw", draw_id)
        validate_payment(DrawStatus(draw.status))
        paid = await self._repo.mark_draw_paid(draw_id, datetime.now(UTC))
        await self._audit.write(
            actor,
            "draw.paid",
            "draws",
            draw_id,
            {"status": {"from": DrawStatus.PENDING.value, "to": DrawStatus.PAID.value}},
        )
        return paid
