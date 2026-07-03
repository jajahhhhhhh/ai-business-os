"""Phase A renovation endpoints: sites, contractors, quotations, draws,
milestones, and bank-alert reconciliation (M1)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from src.application.bank_transactions import BankTransactionUseCases
from src.application.renovation import RenovationUseCases, SiteSpendSummary
from src.application.repositories import BankTransactionRow
from src.infrastructure.audit import SqlAuditWriter
from src.infrastructure.repositories import (
    BankTransactionSqlRepository,
    RenovationSqlRepository,
)
from src.interfaces.dependencies import PrincipalDep, SessionDep
from src.interfaces.schemas import (
    BankAlertIngest,
    BankTransactionMatchIn,
    BankTransactionOut,
    CategorySpendOut,
    ContractorCreate,
    ContractorOut,
    DrawCreate,
    DrawDisplayOut,
    DrawOut,
    MilestoneCreate,
    MilestoneOut,
    MilestoneUpdate,
    QuotationCreate,
    QuotationOut,
    SiteCreate,
    SiteOut,
    SiteSummaryOut,
    SiteWithSpendOut,
    SpendSummaryOut,
)

RAW_EXCERPT_LEN = 200

router = APIRouter(prefix="/renovation", tags=["renovation"])


def _use_cases(session: SessionDep) -> RenovationUseCases:
    return RenovationUseCases(RenovationSqlRepository(session), SqlAuditWriter(session))


def _bank_use_cases(session: SessionDep) -> BankTransactionUseCases:
    return BankTransactionUseCases(
        BankTransactionSqlRepository(session),
        SqlAuditWriter(session),
        _use_cases(session),
    )


UseCasesDep = Annotated[RenovationUseCases, Depends(_use_cases)]
BankUseCasesDep = Annotated[BankTransactionUseCases, Depends(_bank_use_cases)]


def _site_out(summary: SiteSpendSummary) -> SiteWithSpendOut:
    return SiteWithSpendOut(
        id=summary.id,
        name=summary.name,
        location=summary.location,
        budget_thb=summary.budget_thb,
        spend_summary=SpendSummaryOut(
            spent_thb=summary.total_paid_thb,
            outstanding_thb=summary.total_pending_thb,
        ),
    )


def _bank_tx_out(tx: BankTransactionRow) -> BankTransactionOut:
    return BankTransactionOut(
        id=tx.id,
        occurred_at=tx.occurred_at,
        amount_thb=tx.amount_thb,
        direction=tx.direction,
        bank=tx.bank,
        account_tail=tx.account_tail,
        status=tx.status,
        matched_draw_id=tx.matched_draw_id,
        ambiguous_match=tx.ambiguous_match,
        raw_excerpt=tx.raw_text[:RAW_EXCERPT_LEN],
        created_at=tx.created_at,
    )


# ------------------------------------------------------------------ sites


@router.get("/sites", response_model=list[SiteWithSpendOut])
async def list_sites(use_cases: UseCasesDep) -> list[SiteWithSpendOut]:
    return [_site_out(summary) for summary in await use_cases.list_sites_with_spend()]


@router.post("/sites", response_model=SiteOut, status_code=201)
async def create_site(
    payload: SiteCreate, use_cases: UseCasesDep, principal: PrincipalDep
) -> SiteOut:
    site = await use_cases.create_site(
        payload.name, payload.location, payload.budget_thb, principal.actor
    )
    return SiteOut.model_validate(site)


@router.get("/sites/{site_id}/summary", response_model=SiteSummaryOut)
async def site_summary(site_id: uuid.UUID, use_cases: UseCasesDep) -> SiteSummaryOut:
    summary = await use_cases.site_summary(site_id)
    draws = await use_cases.list_draws_display(site_id=site_id, status=None)
    milestones = await use_cases.list_milestones(site_id)
    return SiteSummaryOut(
        site=_site_out(summary),
        spent_thb=summary.total_paid_thb,
        outstanding_draws_thb=summary.total_pending_thb,
        spend_by_category=[
            CategorySpendOut(
                category=cat.category, quoted_thb=cat.quoted_thb, spent_thb=cat.paid_thb
            )
            for cat in summary.categories
        ],
        draws=[DrawDisplayOut.model_validate(d) for d in draws],
        milestones=[MilestoneOut.model_validate(m) for m in milestones],
    )


# ------------------------------------------------------------------ contractors & quotations


@router.post("/contractors", response_model=ContractorOut, status_code=201)
async def create_contractor(
    payload: ContractorCreate, use_cases: UseCasesDep, principal: PrincipalDep
) -> ContractorOut:
    contractor = await use_cases.create_contractor(
        payload.name, payload.contact, payload.line_id, principal.actor
    )
    return ContractorOut.model_validate(contractor)


@router.get("/sites/{site_id}/quotations", response_model=list[QuotationOut])
async def list_quotations(site_id: uuid.UUID, use_cases: UseCasesDep) -> list[QuotationOut]:
    quotations = await use_cases.list_quotations(site_id)
    return [QuotationOut.model_validate(q) for q in quotations]


@router.post("/quotations", response_model=QuotationOut, status_code=201)
async def create_quotation(
    payload: QuotationCreate, use_cases: UseCasesDep, principal: PrincipalDep
) -> QuotationOut:
    quotation = await use_cases.create_quotation(
        payload.site_id,
        payload.contractor_id,
        payload.category,
        payload.amount_thb,
        payload.status,
        principal.actor,
    )
    return QuotationOut.model_validate(quotation)


# ------------------------------------------------------------------ draws


@router.get("/draws", response_model=list[DrawDisplayOut])
async def list_draws(
    use_cases: UseCasesDep,
    site_id: Annotated[uuid.UUID | None, Query()] = None,
    status: Annotated[str | None, Query(max_length=20)] = None,
) -> list[DrawDisplayOut]:
    draws = await use_cases.list_draws_display(site_id=site_id, status=status)
    return [DrawDisplayOut.model_validate(d) for d in draws]


@router.post("/draws", response_model=DrawOut, status_code=201)
async def create_draw(
    payload: DrawCreate, use_cases: UseCasesDep, principal: PrincipalDep
) -> DrawOut:
    draw = await use_cases.create_draw(payload.quotation_id, payload.amount_thb, principal.actor)
    return DrawOut.model_validate(draw)


@router.post("/draws/{draw_id}/pay", response_model=DrawOut)
async def pay_draw(draw_id: uuid.UUID, use_cases: UseCasesDep, principal: PrincipalDep) -> DrawOut:
    return DrawOut.model_validate(await use_cases.pay_draw(draw_id, principal.actor))


# ------------------------------------------------------------------ milestones


@router.get("/sites/{site_id}/milestones", response_model=list[MilestoneOut])
async def list_milestones(site_id: uuid.UUID, use_cases: UseCasesDep) -> list[MilestoneOut]:
    milestones = await use_cases.list_milestones(site_id)
    return [MilestoneOut.model_validate(m) for m in milestones]


@router.post("/sites/{site_id}/milestones", response_model=MilestoneOut, status_code=201)
async def create_milestone(
    site_id: uuid.UUID,
    payload: MilestoneCreate,
    use_cases: UseCasesDep,
    principal: PrincipalDep,
) -> MilestoneOut:
    milestone = await use_cases.create_milestone(
        site_id, payload.name, payload.planned_date, principal.actor
    )
    return MilestoneOut.model_validate(milestone)


@router.patch("/milestones/{milestone_id}", response_model=MilestoneOut)
async def update_milestone(
    milestone_id: uuid.UUID,
    payload: MilestoneUpdate,
    use_cases: UseCasesDep,
    principal: PrincipalDep,
) -> MilestoneOut:
    milestone = await use_cases.update_milestone(
        milestone_id, payload.model_dump(exclude_unset=True), principal.actor
    )
    return MilestoneOut.model_validate(milestone)


# ------------------------------------------------------------------ bank reconciliation


@router.post("/bank-alerts:ingest", response_model=BankTransactionOut, status_code=201)
async def ingest_bank_alert(
    payload: BankAlertIngest,
    response: Response,
    use_cases: BankUseCasesDep,
    principal: PrincipalDep,
) -> BankTransactionOut:
    result = await use_cases.ingest_alert(payload.raw_text, payload.source, principal.actor)
    if not result.created:  # dedup hit: same alert forwarded twice
        response.status_code = 200
    return _bank_tx_out(result.transaction)


@router.get("/bank-transactions", response_model=list[BankTransactionOut])
async def list_bank_transactions(
    use_cases: BankUseCasesDep,
    status: Annotated[str | None, Query(max_length=20)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[BankTransactionOut]:
    return [_bank_tx_out(tx) for tx in await use_cases.list_transactions(status, limit)]


@router.post("/bank-transactions/{tx_id}/confirm", response_model=BankTransactionOut)
async def confirm_bank_transaction(
    tx_id: uuid.UUID, use_cases: BankUseCasesDep, principal: PrincipalDep
) -> BankTransactionOut:
    return _bank_tx_out(await use_cases.confirm(tx_id, principal.actor))


@router.post("/bank-transactions/{tx_id}/ignore", response_model=BankTransactionOut)
async def ignore_bank_transaction(
    tx_id: uuid.UUID, use_cases: BankUseCasesDep, principal: PrincipalDep
) -> BankTransactionOut:
    return _bank_tx_out(await use_cases.ignore(tx_id, principal.actor))


@router.post("/bank-transactions/{tx_id}/match", response_model=BankTransactionOut)
async def match_bank_transaction(
    tx_id: uuid.UUID,
    payload: BankTransactionMatchIn,
    use_cases: BankUseCasesDep,
    principal: PrincipalDep,
) -> BankTransactionOut:
    return _bank_tx_out(await use_cases.match(tx_id, payload.draw_id, principal.actor))
