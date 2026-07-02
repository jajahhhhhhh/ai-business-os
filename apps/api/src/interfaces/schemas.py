"""Pydantic request/response schemas for all /v1 routers."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, PlainSerializer

from src.domain.leads import LeadStage

# Money OUT fields serialize as JSON numbers (the dashboard does arithmetic on
# them); request bodies keep exact Decimal parsing. Display rounding only —
# the database preserves exact numeric(14,2) values.
THB = Annotated[Decimal, PlainSerializer(float, return_type=float, when_used="json")]
USD = Annotated[Decimal, PlainSerializer(float, return_type=float, when_used="json")]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ------------------------------------------------------------------ health


class HealthOut(BaseModel):
    status: str
    version: str
    env: str


class DependencyStatus(BaseModel):
    status: str
    detail: str | None = None


class ReadyOut(BaseModel):
    status: str
    checks: dict[str, DependencyStatus]


# ------------------------------------------------------------------ renovation


class SiteCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    location: str | None = None
    budget_thb: Decimal | None = Field(default=None, ge=0)


class SiteOut(ORMModel):
    id: uuid.UUID
    name: str
    location: str | None
    budget_thb: THB | None
    created_at: datetime


class ContractorCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    contact: str | None = None
    line_id: str | None = None


class ContractorOut(ORMModel):
    id: uuid.UUID
    name: str
    contact: str | None
    line_id: str | None


# Response shapes below mirror apps/web/lib/types.ts (Site, SiteSummary,
# SpendSummary, CategorySpend) — the dashboard is typed against them exactly.


class SpendSummaryOut(BaseModel):
    spent_thb: THB
    outstanding_thb: THB


class SiteWithSpendOut(BaseModel):
    id: uuid.UUID
    name: str
    location: str | None
    budget_thb: THB | None
    spend_summary: SpendSummaryOut | None


class CategorySpendOut(BaseModel):
    category: str
    quoted_thb: THB
    spent_thb: THB


# (SiteSummaryOut is defined after DrawDisplayOut/MilestoneOut below.)


class QuotationCreate(BaseModel):
    site_id: uuid.UUID
    contractor_id: uuid.UUID
    category: str = Field(min_length=1, max_length=100)
    amount_thb: Decimal = Field(gt=0)
    status: str = "pending"


class QuotationOut(ORMModel):
    id: uuid.UUID
    site_id: uuid.UUID
    contractor_id: uuid.UUID
    category: str
    amount_thb: THB
    status: str
    created_at: datetime


class DrawCreate(BaseModel):
    quotation_id: uuid.UUID
    amount_thb: Decimal = Field(gt=0)


class DrawOut(ORMModel):
    id: uuid.UUID
    quotation_id: uuid.UUID
    seq: int
    amount_thb: THB
    status: str
    requested_at: datetime
    paid_at: datetime | None


class DrawDisplayOut(ORMModel):
    """A draw enriched with quotation/contractor/site context for display."""

    id: uuid.UUID
    seq: int
    amount_thb: THB
    status: str
    requested_at: datetime
    paid_at: datetime | None
    quotation_id: uuid.UUID
    category: str
    contractor_name: str
    site_id: uuid.UUID
    site_name: str


MilestoneStatus = Literal["planned", "in_progress", "done", "delayed"]


class MilestoneCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    planned_date: date | None = None


class MilestoneUpdate(BaseModel):
    """PATCH body: only fields explicitly provided are applied."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    planned_date: date | None = None
    actual_date: date | None = None
    status: MilestoneStatus | None = None


class MilestoneOut(ORMModel):
    id: uuid.UUID
    site_id: uuid.UUID
    name: str
    planned_date: date | None
    actual_date: date | None
    status: str
    created_at: datetime


class SiteSummaryOut(BaseModel):
    site: SiteWithSpendOut
    spent_thb: THB
    outstanding_draws_thb: THB
    spend_by_category: list[CategorySpendOut]
    draws: list[DrawDisplayOut]
    milestones: list[MilestoneOut]


# ------------------------------------------------------------------ bank transactions


class BankAlertIngest(BaseModel):
    raw_text: str = Field(min_length=1, max_length=20_000)
    source: Literal["manual", "gmail"] = "manual"


class BankTransactionMatchIn(BaseModel):
    draw_id: uuid.UUID


class BankTransactionOut(BaseModel):
    id: uuid.UUID
    occurred_at: datetime
    amount_thb: THB
    direction: str
    bank: str
    account_tail: str | None
    status: str
    matched_draw_id: uuid.UUID | None
    ambiguous_match: bool
    raw_excerpt: str
    created_at: datetime


# ------------------------------------------------------------------ leads


class LeadOut(ORMModel):
    # contact_json is intentionally omitted: it is PII (PDPA-minimized surface).
    id: uuid.UUID
    kind: str
    name: str
    locale: str | None
    intent_score: int
    stage: str
    first_seen_at: datetime
    last_activity_at: datetime | None
    created_at: datetime


class LeadListOut(BaseModel):
    items: list[LeadOut]
    next_cursor: str | None


class StageChangeIn(BaseModel):
    stage: LeadStage


# ------------------------------------------------------------------ competitors


class CompetitorCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: str | None = None
    website: str | None = None
    listing_urls: dict[str, Any] | None = None


class CompetitorOut(ORMModel):
    id: uuid.UUID
    name: str
    kind: str | None
    website: str | None
    active: bool
    created_at: datetime


class ChangeEventOut(ORMModel):
    id: uuid.UUID
    competitor_id: uuid.UUID
    snapshot_id: uuid.UUID | None
    category: str
    summary: str
    severity: str
    detected_at: datetime


# ------------------------------------------------------------------ agents & automation


class AgentRunOut(ORMModel):
    id: uuid.UUID
    agent: str
    task_id: str | None
    status: str
    model: str | None
    tokens_in: int
    tokens_out: int
    cost_usd: USD
    started_at: datetime
    finished_at: datetime | None
    error: str | None


class ReportOut(ORMModel):
    id: uuid.UUID
    kind: str
    period: str | None
    lang: str
    storage_key: str | None
    body: str | None = None
    generated_at: datetime = Field(validation_alias=AliasChoices("generated_at", "created_at"))
    sent_at: datetime | None
    created_at: datetime


class SnapshotReportOut(BaseModel):
    id: uuid.UUID
    kind: str
    period: str | None
    lang: str
    body: str
    line_sent: bool
    created_at: datetime


class JobOut(ORMModel):
    id: uuid.UUID
    name: str
    cron: str
    enabled: bool
    last_run_at: datetime | None
    last_status: str | None


class JobRunAccepted(BaseModel):
    job_id: uuid.UUID
    status: str = "accepted"
    detail: str
