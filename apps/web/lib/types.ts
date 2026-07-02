/**
 * API types mirroring the FastAPI contract (docs/ARCHITECTURE.md §7 schema, §11 API design).
 *
 * Conventions assumed from the backend:
 * - IDs are UUIDv7 strings, timestamps are ISO-8601 strings (UTC).
 * - Cursor-paginated collections use the { items, next_cursor } envelope.
 * - Amounts are THB integers (satang not tracked in Phase A); agent cost is USD.
 */

export interface Health {
  status: string;
  version?: string;
}

/** Cursor-paginated list envelope. */
export interface Paginated<T> {
  items: T[];
  next_cursor: string | null;
}

// ---------------------------------------------------------------------------
// Phase A — renovation
// ---------------------------------------------------------------------------

export interface SpendSummary {
  spent_thb: number;
  outstanding_thb: number;
}

export interface Site {
  id: string;
  name: string;
  location: string;
  budget_thb: number;
  spend_summary: SpendSummary | null;
}

export type DrawStatus = "requested" | "approved" | "paid" | "rejected";

export interface Draw {
  id: string;
  quotation_id: string;
  seq: number;
  contractor_name: string;
  amount_thb: number;
  status: DrawStatus;
  requested_at: string;
  paid_at: string | null;
}

export type MilestoneStatus = "planned" | "in_progress" | "done" | "delayed";

export interface Milestone {
  id: string;
  site_id: string;
  name: string;
  planned_date: string;
  actual_date: string | null;
  status: MilestoneStatus;
}

export interface CategorySpend {
  category: string;
  quoted_thb: number;
  spent_thb: number;
}

/** GET /v1/renovation/sites/{id}/summary */
export interface SiteSummary {
  site: Site;
  spent_thb: number;
  outstanding_draws_thb: number;
  spend_by_category: CategorySpend[];
  draws: Draw[];
  milestones: Milestone[];
}

// ---------------------------------------------------------------------------
// Phase A — renovation write flows (M1)
// ---------------------------------------------------------------------------

export interface Contractor {
  id: string;
  name: string;
  contact: string | null;
  line_id: string | null;
}

/** POST /v1/renovation/contractors */
export interface ContractorCreate {
  name: string;
  contact?: string;
  line_id?: string;
}

/** Backend stores quotation status as a free string (default "pending"). */
export interface Quotation {
  id: string;
  site_id: string;
  contractor_id: string;
  category: string;
  amount_thb: number;
  status: string;
}

/** POST /v1/renovation/quotations */
export interface QuotationCreate {
  site_id: string;
  contractor_id: string;
  category: string;
  amount_thb: number;
}

/**
 * Status vocabulary of GET /v1/renovation/draws (backend domain model).
 * Note: differs from the legacy `DrawStatus` used by the site-summary payload.
 */
export type DrawRowStatus = "pending" | "paid" | "cancelled";

/** GET /v1/renovation/draws — draw rows enriched with quotation/site context. */
export interface DrawRow {
  id: string;
  seq: number;
  amount_thb: number;
  status: DrawRowStatus;
  requested_at: string;
  paid_at: string | null;
  quotation_id: string;
  category: string;
  contractor_name: string;
  site_id: string;
  site_name: string;
}

export interface DrawListParams {
  site_id?: string;
  status?: DrawRowStatus;
}

/** POST /v1/renovation/draws */
export interface DrawCreate {
  quotation_id: string;
  amount_thb: number;
}

/** POST /v1/renovation/sites/{siteId}/milestones */
export interface MilestoneCreate {
  name: string;
  planned_date: string;
}

/** PATCH /v1/renovation/milestones/{id} — all fields optional. */
export interface MilestonePatch {
  name?: string;
  planned_date?: string;
  actual_date?: string;
  status?: MilestoneStatus;
}

// ---------------------------------------------------------------------------
// Payments — bank alerts & transactions (M1)
// ---------------------------------------------------------------------------

export type BankTransactionDirection = "in" | "out";

export type BankTransactionStatus = "unmatched" | "matched" | "confirmed" | "ignored";

export interface BankTransaction {
  id: string;
  occurred_at: string;
  amount_thb: number;
  direction: BankTransactionDirection;
  bank: string;
  account_tail: string | null;
  status: BankTransactionStatus;
  matched_draw_id: string | null;
  ambiguous_match: boolean;
  raw_excerpt: string;
  created_at: string;
}

export interface BankTransactionListParams {
  status?: BankTransactionStatus;
  limit?: number;
}

/** POST /v1/renovation/bank-alerts:ingest */
export interface BankAlertIngest {
  raw_text: string;
  source: "manual";
}

/** POST /v1/reports/daily-snapshot:generate */
export interface DailySnapshot {
  id: string;
  kind: string;
  lang: string;
  body: string;
  line_sent: boolean;
}

// ---------------------------------------------------------------------------
// Leads (Phase C schema, ready now)
// ---------------------------------------------------------------------------

export type LeadStage = "discovered" | "qualified" | "contacted" | "won" | "lost";

export type LeadKind = "guest" | "longstay" | "b2b" | "supplier";

export interface Lead {
  id: string;
  name: string;
  kind: LeadKind;
  intent_score: number;
  stage: LeadStage;
  source: string | null;
  locale: string | null;
  first_seen_at: string;
  last_activity_at: string | null;
}

export interface LeadListParams {
  stage?: LeadStage;
  min_score?: number;
  q?: string;
  cursor?: string;
}

// ---------------------------------------------------------------------------
// Competitor intelligence
// ---------------------------------------------------------------------------

export interface Competitor {
  id: string;
  name: string;
  kind: string;
  website: string;
  active: boolean;
}

export type ChangeSeverity = "low" | "medium" | "high" | "critical";

export interface CompetitorChange {
  id: string;
  competitor_id: string;
  category: string;
  summary: string;
  severity: ChangeSeverity;
  detected_at: string;
}

// ---------------------------------------------------------------------------
// Agents & automation
// ---------------------------------------------------------------------------

export type AgentRunStatus = "queued" | "running" | "succeeded" | "failed";

export interface AgentRun {
  id: string;
  agent: string;
  task_id: string | null;
  status: AgentRunStatus;
  model: string;
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
  started_at: string;
  finished_at: string | null;
  error: string | null;
}

export interface AgentRunListParams {
  agent?: string;
  status?: AgentRunStatus;
}

export interface Job {
  id: string;
  name: string;
  cron: string;
  enabled: boolean;
  last_run_at: string | null;
  last_status: "success" | "failed" | null;
}

export type ReportKind = "daily" | "weekly" | "monthly";

export interface Report {
  id: string;
  kind: ReportKind;
  period: string;
  lang: string;
  storage_key: string;
  generated_at: string;
  sent_at: string | null;
  /** Inline Thai report body (daily snapshots since M1) — absent on older rows. */
  body?: string | null;
}

export interface ReportListParams {
  kind?: ReportKind;
}
