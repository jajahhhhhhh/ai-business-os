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
// Knowledge base (M2) — documents, ingestion status, hybrid search
// ---------------------------------------------------------------------------

export type KbDocumentStatus = "pending" | "parsing" | "indexed" | "failed";

export type KbLang = "th" | "en";

/** POST /v1/kb/documents (202) · GET /v1/kb/documents list item. */
export interface KbDocument {
  id: string;
  title: string;
  mime: string;
  lang: string | null;
  status: KbDocumentStatus;
  ocr_done: boolean;
  meili_indexed: boolean;
  embedded: boolean;
  size_bytes: number | null;
  source: string;
  error: string | null;
  created_at: string;
}

/** GET /v1/kb/documents/{id} — document enriched with chunk count. */
export interface KbDocumentDetail extends KbDocument {
  chunk_count: number;
}

export interface KbDocumentListParams {
  status?: KbDocumentStatus;
  limit?: number;
}

/** POST /v1/kb/documents — multipart form fields. */
export interface KbDocumentUpload {
  file: File;
  title?: string;
  lang?: KbLang;
}

export type KbSearchMode = "hybrid" | "keyword" | "semantic";

export interface KbSearchParams {
  q: string;
  mode?: KbSearchMode;
  limit?: number;
}

export interface KbSearchResult {
  chunk_id: string;
  document_id: string;
  document_title: string;
  seq: number;
  text: string;
  score: number;
  /** Which index matched this chunk, e.g. ["keyword", "vector"]. */
  matched_by: string[];
}

/** GET /v1/kb/search — degraded=true means semantic side was unavailable. */
export interface KbSearchResponse {
  query: string;
  mode: string;
  degraded: boolean;
  results: KbSearchResult[];
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
  kind?: LeadKind;
  min_score?: number;
  q?: string;
  cursor?: string;
  limit?: number;
}

// ---------------------------------------------------------------------------
// Lead discovery CRM (M5) — detail, events, scoring, sources
// ---------------------------------------------------------------------------

/**
 * Owner-only public contact info (PDPA: minimal, auto-anonymized after 18
 * months of inactivity). null when no contact was captured or already erased.
 */
export interface LeadContact {
  /** e.g. "reddit" | "rss". */
  platform: string;
  handle: string;
  url: string;
}

/** Timeline entry inside GET /v1/leads/{id} — type is a free string. */
export interface LeadEvent {
  type: string;
  payload: Record<string, unknown>;
  occurred_at: string;
}

/** Latest intent-score snapshot with the feature breakdown that produced it. */
export interface LeadScoreInfo {
  value: number;
  model_version: string;
  features: Record<string, unknown>;
}

/** GET /v1/leads/{id} — Lead enriched with contact, timeline and scoring. */
export interface LeadDetail extends Lead {
  contact: LeadContact | null;
  events: LeadEvent[];
  score: LeadScoreInfo | null;
  /** LLM follow-up suggestion (Thai), null until the classifier has run. */
  suggestion: string | null;
}

/**
 * Source types accepted by the lead collector. Reddit goes through the
 * official API only; RSS is fetched directly (ToS compliance gate applies).
 */
export type LeadSourceType = "rss" | "reddit";

/** Collector config — subreddit/query for reddit sources. */
export interface LeadSourceConfig {
  subreddit?: string;
  query?: string;
}

/** GET /v1/sources list item · POST/PATCH response body. */
export interface LeadSource {
  id: string;
  name: string;
  type: LeadSourceType;
  url: string | null;
  config: LeadSourceConfig | null;
  /** ToS policy verdict recorded by the compliance gate. */
  tos_policy: string;
  rate_limit_per_hr: number;
  enabled: boolean;
  last_checked_at: string | null;
  /** Collector outcome — free string, labelled via sourceStatusLabel(). */
  last_status: string | null;
  created_at: string;
}

/**
 * POST /v1/sources — responds 422 problem+json (Thai detail) when the URL is
 * a ToS-blocked domain.
 */
export interface LeadSourceCreate {
  name: string;
  type: LeadSourceType;
  url?: string;
  config?: LeadSourceConfig;
  rate_limit_per_hr?: number;
}

/** PATCH /v1/sources/{id} — all fields optional. */
export interface LeadSourcePatch {
  enabled?: boolean;
  name?: string;
  url?: string;
  config?: LeadSourceConfig;
  rate_limit_per_hr?: number;
}

/** POST /v1/sources/{id}:collect → 202 accepted. */
export interface CollectResponse {
  detail: string;
}

// ---------------------------------------------------------------------------
// Competitor intelligence (M3) — registry with nested sources, change feed
// ---------------------------------------------------------------------------

/**
 * Known competitor kinds. The API stores `kind` as a free string — this union
 * is the UI vocabulary offered by the create form (see COMPETITOR_KIND_LABELS).
 */
export type CompetitorKind = "villa" | "hotel" | "aspirational" | "other";

/**
 * Source types accepted by the API. Facebook/Airbnb/Booking/Agoda URLs are
 * refused with a 422 problem+json (Thai detail) by the ToS compliance gate.
 */
export type CompetitorSourceType = "website" | "rss";

/** Nested source row inside GET /v1/competitors · POST .../sources response. */
export interface CompetitorSource {
  id: string;
  type: CompetitorSourceType;
  url: string;
  enabled: boolean;
  /** ToS policy verdict recorded by the compliance gate. */
  tos_policy: string;
  last_checked_at: string | null;
  /**
   * Collector outcome — free string, e.g. "baseline" | "unchanged" |
   * "changed" | "error" | "blocked". Labelled via sourceStatusLabel().
   */
  last_status: string | null;
}

/** GET /v1/competitors list item · POST/PATCH response body. */
export interface Competitor {
  id: string;
  name: string;
  kind: string | null;
  website: string | null;
  active: boolean;
  created_at: string;
  sources: CompetitorSource[];
}

/** Source item accepted by POST /v1/competitors and POST .../sources. */
export interface CompetitorSourceCreate {
  type: CompetitorSourceType;
  url: string;
}

/**
 * POST /v1/competitors — responds 422 problem+json (Thai detail) when a
 * source URL is ToS-blocked (Facebook / Airbnb / Booking / Agoda).
 */
export interface CompetitorCreate {
  name: string;
  kind?: string;
  website?: string;
  sources?: CompetitorSourceCreate[];
}

/** PATCH /v1/competitors/{id} — all fields optional. */
export interface CompetitorPatch {
  name?: string;
  kind?: string;
  website?: string;
  active?: boolean;
}

export type ChangeSeverity = "low" | "medium" | "high" | "critical";

export type ChangeCategory = "pricing" | "promotion" | "content" | "listing" | "other";

/** GET /v1/competitors/changes — newest first, competitor name denormalized in. */
export interface CompetitorChange {
  id: string;
  competitor_id: string;
  competitor_name: string;
  category: ChangeCategory;
  summary: string;
  severity: ChangeSeverity;
  detected_at: string;
}

export interface CompetitorChangeListParams {
  /** ISO-8601 lower bound on detected_at. */
  since?: string;
  severity?: ChangeSeverity;
  limit?: number;
}

/** POST /v1/competitors/{id}:check → 202 accepted. */
export interface CheckResponse {
  detail: string;
}

/** POST /v1/reports/weekly-competitor:generate → 201. */
export interface WeeklyCompetitorReport {
  id: string;
  kind: string;
  period: string;
  lang: string;
  body: string;
  line_sent: boolean;
  created_at: string;
}

// ---------------------------------------------------------------------------
// Agents & automation
// ---------------------------------------------------------------------------

export type AgentRunStatus =
  | "queued"
  | "running"
  | "succeeded"
  | "failed"
  | "parked"
  | "over_budget";

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
  limit?: number;
}

/**
 * GET /v1/agents/costs?days=7 — one row per agent × Bangkok day, ordered by
 * agent then day. `budget_usd` is the daily cap (null = no cap configured).
 */
export interface AgentCost {
  agent: string;
  /** Bangkok-local day, "YYYY-MM-DD". */
  day: string;
  cost_usd: number;
  tokens_in: number;
  tokens_out: number;
  runs: number;
  budget_usd: number | null;
}

/** GET /v1/agents/evals — QA rubric scores per run, newest first. */
export interface AgentEval {
  id: string;
  run_id: string;
  agent: string;
  rubric: string;
  /** 0–100. */
  score: number;
  notes: string | null;
  created_at: string;
}

export interface AgentEvalListParams {
  agent?: string;
  limit?: number;
}

/**
 * Task names accepted by POST /v1/agents/{name}:trigger — unknown names get a
 * 404 problem+json from the API.
 */
export type AgentTaskName =
  | "analytics-daily"
  | "analytics-weekly"
  | "planner"
  | "memory-consolidate"
  | "memory-capture"
  | "qa-evaluate";

/** POST /v1/agents/{name}:trigger → 202 accepted. */
export interface TriggerResponse {
  agent: string;
  detail: string;
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
