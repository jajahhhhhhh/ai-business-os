"""Pydantic request/response schemas for all /v1 routers."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.domain.leads import LeadStage


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
    budget_thb: Decimal | None
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


class CategorySpendOut(ORMModel):
    category: str
    quoted_thb: Decimal
    paid_thb: Decimal
    pending_thb: Decimal


class SiteSpendOut(ORMModel):
    id: uuid.UUID
    name: str
    location: str | None
    budget_thb: Decimal | None
    categories: list[CategorySpendOut]
    total_quoted_thb: Decimal
    total_paid_thb: Decimal
    total_pending_thb: Decimal


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
    amount_thb: Decimal
    status: str
    created_at: datetime


class DrawCreate(BaseModel):
    quotation_id: uuid.UUID
    amount_thb: Decimal = Field(gt=0)


class DrawOut(ORMModel):
    id: uuid.UUID
    quotation_id: uuid.UUID
    seq: int
    amount_thb: Decimal
    status: str
    requested_at: datetime
    paid_at: datetime | None


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
    cost_usd: Decimal
    started_at: datetime
    finished_at: datetime | None
    error: str | None


class ReportOut(ORMModel):
    id: uuid.UUID
    kind: str
    period: str | None
    lang: str
    storage_key: str | None
    sent_at: datetime | None
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
