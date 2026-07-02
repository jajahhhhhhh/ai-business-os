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
}

export interface ReportListParams {
  kind?: ReportKind;
}
