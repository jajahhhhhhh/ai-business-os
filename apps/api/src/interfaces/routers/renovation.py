"""Phase A renovation endpoints: sites, contractors, quotations, draws."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from src.application.renovation import RenovationUseCases
from src.infrastructure.audit import SqlAuditWriter
from src.infrastructure.repositories import RenovationSqlRepository
from src.interfaces.dependencies import PrincipalDep, SessionDep
from src.interfaces.schemas import (
    ContractorCreate,
    ContractorOut,
    DrawCreate,
    DrawOut,
    QuotationCreate,
    QuotationOut,
    SiteCreate,
    SiteOut,
    SiteSpendOut,
)

router = APIRouter(prefix="/renovation", tags=["renovation"])


def _use_cases(session: SessionDep) -> RenovationUseCases:
    return RenovationUseCases(RenovationSqlRepository(session), SqlAuditWriter(session))


UseCasesDep = Annotated[RenovationUseCases, Depends(_use_cases)]


@router.get("/sites", response_model=list[SiteSpendOut])
async def list_sites(use_cases: UseCasesDep) -> list[SiteSpendOut]:
    summaries = await use_cases.list_sites_with_spend()
    return [SiteSpendOut.model_validate(summary) for summary in summaries]


@router.post("/sites", response_model=SiteOut, status_code=201)
async def create_site(
    payload: SiteCreate, use_cases: UseCasesDep, principal: PrincipalDep
) -> SiteOut:
    site = await use_cases.create_site(
        payload.name, payload.location, payload.budget_thb, principal.actor
    )
    return SiteOut.model_validate(site)


@router.get("/sites/{site_id}/summary", response_model=SiteSpendOut)
async def site_summary(site_id: uuid.UUID, use_cases: UseCasesDep) -> SiteSpendOut:
    return SiteSpendOut.model_validate(await use_cases.site_summary(site_id))


@router.post("/contractors", response_model=ContractorOut, status_code=201)
async def create_contractor(
    payload: ContractorCreate, use_cases: UseCasesDep, principal: PrincipalDep
) -> ContractorOut:
    contractor = await use_cases.create_contractor(
        payload.name, payload.contact, payload.line_id, principal.actor
    )
    return ContractorOut.model_validate(contractor)


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


@router.post("/draws", response_model=DrawOut, status_code=201)
async def create_draw(
    payload: DrawCreate, use_cases: UseCasesDep, principal: PrincipalDep
) -> DrawOut:
    draw = await use_cases.create_draw(payload.quotation_id, payload.amount_thb, principal.actor)
    return DrawOut.model_validate(draw)


@router.post("/draws/{draw_id}/pay", response_model=DrawOut)
async def pay_draw(
    draw_id: uuid.UUID, use_cases: UseCasesDep, principal: PrincipalDep
) -> DrawOut:
    return DrawOut.model_validate(await use_cases.pay_draw(draw_id, principal.actor))
