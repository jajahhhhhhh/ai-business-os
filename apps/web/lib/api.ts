/**
 * Typed fetch client for the FastAPI backend (docs/ARCHITECTURE.md §11).
 *
 * Server-component friendly: every call uses `cache: 'no-store'` so pages are
 * always dynamic and never try to reach the API during `next build`.
 * Callers should wrap calls in `safe()` so an unreachable API degrades to an
 * EmptyState instead of crashing the page.
 */

import type {
  AgentCost,
  AgentEval,
  AgentEvalListParams,
  AgentRun,
  AgentRunListParams,
  AgentTaskName,
  BankAlertIngest,
  BankTransaction,
  BankTransactionListParams,
  CheckResponse,
  Competitor,
  CompetitorChange,
  CompetitorChangeListParams,
  CompetitorCreate,
  CompetitorPatch,
  CompetitorSource,
  CompetitorSourceCreate,
  Contractor,
  ContractorCreate,
  DailySnapshot,
  DrawCreate,
  DrawListParams,
  DrawRow,
  Health,
  Job,
  KbDocument,
  KbDocumentDetail,
  KbDocumentListParams,
  KbDocumentUpload,
  KbSearchParams,
  KbSearchResponse,
  Lead,
  LeadListParams,
  Milestone,
  MilestoneCreate,
  MilestonePatch,
  Paginated,
  Quotation,
  QuotationCreate,
  Report,
  ReportListParams,
  Site,
  SiteSummary,
  TriggerResponse,
  WeeklyCompetitorReport,
} from "./types";

const DEFAULT_BASE_URL = "http://localhost:8000";
const REQUEST_TIMEOUT_MS = 5000;
/** Mutations may hit the LLM (daily snapshot) — allow more headroom than GETs. */
const MUTATION_TIMEOUT_MS = 20000;
/** Hybrid search embeds the query server-side — slower than a plain GET. */
const SEARCH_TIMEOUT_MS = 15000;
/** File uploads may push 25 MB over home upstream — be generous. */
const UPLOAD_TIMEOUT_MS = 60000;

export function apiBaseUrl(): string {
  return process.env.NEXT_PUBLIC_API_URL ?? DEFAULT_BASE_URL;
}

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

type QueryValue = string | number | boolean | undefined;

async function get<T>(
  path: string,
  query?: Record<string, QueryValue>,
  timeoutMs: number = REQUEST_TIMEOUT_MS,
): Promise<T> {
  const url = new URL(`/v1${path}`, apiBaseUrl());
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== "") {
        url.searchParams.set(key, String(value));
      }
    }
  }

  const res = await fetch(url.toString(), {
    cache: "no-store",
    headers: { Accept: "application/json" },
    signal: AbortSignal.timeout(timeoutMs),
  });

  if (!res.ok) {
    throw new ApiError(res.status, `GET ${url.pathname} → HTTP ${res.status}`);
  }
  return (await res.json()) as T;
}

/**
 * Extract a human-readable message from a FastAPI problem+json error body.
 * Falls back to a generic Thai message — mutation errors are shown inline in
 * the UI, so the fallback must be owner-readable.
 */
async function problemDetail(res: Response): Promise<string> {
  const fallback = `คำขอไม่สำเร็จ (HTTP ${res.status}) — ลองอีกครั้ง`;
  try {
    const body: unknown = await res.json();
    if (typeof body !== "object" || body === null) return fallback;
    const problem = body as { detail?: unknown; title?: unknown };
    if (typeof problem.detail === "string" && problem.detail.length > 0) {
      return problem.detail;
    }
    // FastAPI validation errors: detail is a list of { msg, loc, ... }.
    if (Array.isArray(problem.detail)) {
      const messages = problem.detail
        .map((item: unknown) =>
          typeof item === "object" && item !== null && "msg" in item
            ? String((item as { msg: unknown }).msg)
            : null,
        )
        .filter((msg): msg is string => msg !== null);
      if (messages.length > 0) return messages.join(" · ");
    }
    if (typeof problem.title === "string" && problem.title.length > 0) {
      return problem.title;
    }
    return fallback;
  } catch {
    return fallback;
  }
}

/**
 * JSON mutation (POST/PATCH) for `use client` components. Throws `ApiError`
 * whose `message` is the problem+json `detail`, ready to render inline.
 */
async function mutate<T>(
  method: "POST" | "PATCH",
  path: string,
  body?: unknown,
): Promise<T> {
  const url = new URL(`/v1${path}`, apiBaseUrl());

  const res = await fetch(url.toString(), {
    method,
    cache: "no-store",
    headers: {
      Accept: "application/json",
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
    signal: AbortSignal.timeout(MUTATION_TIMEOUT_MS),
  });

  if (!res.ok) {
    throw new ApiError(res.status, await problemDetail(res));
  }
  return (await res.json()) as T;
}

/**
 * DELETE for `use client` components — expects 204 No Content, so the body is
 * never parsed. Throws `ApiError` with the problem+json detail on failure.
 */
async function remove(path: string): Promise<void> {
  const url = new URL(`/v1${path}`, apiBaseUrl());

  const res = await fetch(url.toString(), {
    method: "DELETE",
    cache: "no-store",
    headers: { Accept: "application/json" },
    signal: AbortSignal.timeout(MUTATION_TIMEOUT_MS),
  });

  if (!res.ok) {
    throw new ApiError(res.status, await problemDetail(res));
  }
}

/**
 * Multipart upload (POST FormData) for `use client` components. Throws
 * `ApiError` with the problem+json detail, same as `mutate`.
 *
 * Deliberately does NOT set Content-Type — the browser adds
 * `multipart/form-data; boundary=...` itself, and setting it manually would
 * drop the boundary and break parsing server-side.
 */
async function uploadForm<T>(path: string, form: FormData): Promise<T> {
  const url = new URL(`/v1${path}`, apiBaseUrl());

  const res = await fetch(url.toString(), {
    method: "POST",
    cache: "no-store",
    headers: { Accept: "application/json" },
    body: form,
    signal: AbortSignal.timeout(UPLOAD_TIMEOUT_MS),
  });

  if (!res.ok) {
    throw new ApiError(res.status, await problemDetail(res));
  }
  return (await res.json()) as T;
}

/** Resolve to null instead of throwing — pages must never crash without the API. */
export async function safe<T>(promise: Promise<T>): Promise<T | null> {
  try {
    return await promise;
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Endpoints
// ---------------------------------------------------------------------------

export function getHealth(): Promise<Health> {
  return get<Health>("/health");
}

export function listSites(): Promise<Site[]> {
  return get<Site[]>("/renovation/sites");
}

export function getSiteSummary(siteId: string): Promise<SiteSummary> {
  return get<SiteSummary>(`/renovation/sites/${encodeURIComponent(siteId)}/summary`);
}

export function listLeads(params: LeadListParams = {}): Promise<Paginated<Lead>> {
  return get<Paginated<Lead>>("/leads", {
    stage: params.stage,
    min_score: params.min_score,
    q: params.q,
    cursor: params.cursor,
  });
}

/** GET /v1/competitors — each competitor carries its nested sources. */
export function listCompetitors(): Promise<Competitor[]> {
  return get<Competitor[]>("/competitors");
}

export async function listAgentRuns(
  params: AgentRunListParams = {},
): Promise<Paginated<AgentRun>> {
  // The M0 backend returns a bare array (`list[AgentRunOut]`); ARCHITECTURE §11
  // reserves the { items, next_cursor } envelope. Normalize so both shapes work.
  const data = await get<AgentRun[] | Paginated<AgentRun>>("/agents/runs", {
    agent: params.agent,
    status: params.status,
    limit: params.limit,
  });
  return Array.isArray(data) ? { items: data, next_cursor: null } : data;
}

// ---------------------------------------------------------------------------
// Agent cost dashboard (M4) — reads for server components
// ---------------------------------------------------------------------------

/** GET /v1/agents/costs?days=7 — per-agent daily spend, ordered agent → day. */
export function listAgentCosts(days = 7): Promise<AgentCost[]> {
  return get<AgentCost[]>("/agents/costs", { days });
}

/** GET /v1/agents/evals — QA rubric scores, newest first. */
export function listAgentEvals(params: AgentEvalListParams = {}): Promise<AgentEval[]> {
  return get<AgentEval[]>("/agents/evals", {
    agent: params.agent,
    limit: params.limit,
  });
}

// ---------------------------------------------------------------------------
// Agent cost dashboard (M4) — mutations for `use client` components
// ---------------------------------------------------------------------------

/**
 * POST /v1/agents/{name}:trigger → 202 { agent, detail }. Unknown task names
 * get a 404 problem+json — thrown as ApiError with a display-ready detail.
 */
export function triggerAgentTask(name: AgentTaskName): Promise<TriggerResponse> {
  return mutate<TriggerResponse>("POST", `/agents/${encodeURIComponent(name)}:trigger`);
}

export function listReports(params: ReportListParams = {}): Promise<Report[]> {
  return get<Report[]>("/reports", { kind: params.kind });
}

export function listJobs(): Promise<Job[]> {
  return get<Job[]>("/jobs");
}

// ---------------------------------------------------------------------------
// Renovation write flows (M1) — reads for server components
// ---------------------------------------------------------------------------

export function listSiteQuotations(siteId: string): Promise<Quotation[]> {
  return get<Quotation[]>(`/renovation/sites/${encodeURIComponent(siteId)}/quotations`);
}

export function listDraws(params: DrawListParams = {}): Promise<DrawRow[]> {
  return get<DrawRow[]>("/renovation/draws", {
    site_id: params.site_id,
    status: params.status,
  });
}

export function listSiteMilestones(siteId: string): Promise<Milestone[]> {
  return get<Milestone[]>(`/renovation/sites/${encodeURIComponent(siteId)}/milestones`);
}

export function listBankTransactions(
  params: BankTransactionListParams = {},
): Promise<BankTransaction[]> {
  return get<BankTransaction[]>("/renovation/bank-transactions", {
    status: params.status,
    limit: params.limit,
  });
}

// ---------------------------------------------------------------------------
// Renovation write flows (M1) — mutations for `use client` components.
// All throw ApiError with a display-ready problem+json detail.
// ---------------------------------------------------------------------------

export function createContractor(payload: ContractorCreate): Promise<Contractor> {
  return mutate<Contractor>("POST", "/renovation/contractors", payload);
}

export function createQuotation(payload: QuotationCreate): Promise<Quotation> {
  return mutate<Quotation>("POST", "/renovation/quotations", payload);
}

export async function createDraw(payload: DrawCreate): Promise<void> {
  await mutate<unknown>("POST", "/renovation/draws", payload);
}

export async function payDraw(drawId: string): Promise<void> {
  await mutate<unknown>("POST", `/renovation/draws/${encodeURIComponent(drawId)}/pay`);
}

export async function createMilestone(
  siteId: string,
  payload: MilestoneCreate,
): Promise<void> {
  await mutate<unknown>(
    "POST",
    `/renovation/sites/${encodeURIComponent(siteId)}/milestones`,
    payload,
  );
}

export async function updateMilestone(
  milestoneId: string,
  payload: MilestonePatch,
): Promise<void> {
  await mutate<unknown>(
    "PATCH",
    `/renovation/milestones/${encodeURIComponent(milestoneId)}`,
    payload,
  );
}

export function ingestBankAlert(rawText: string): Promise<BankTransaction> {
  const payload: BankAlertIngest = { raw_text: rawText, source: "manual" };
  return mutate<BankTransaction>("POST", "/renovation/bank-alerts:ingest", payload);
}

export async function confirmBankTransaction(id: string): Promise<void> {
  await mutate<unknown>(
    "POST",
    `/renovation/bank-transactions/${encodeURIComponent(id)}/confirm`,
  );
}

export async function ignoreBankTransaction(id: string): Promise<void> {
  await mutate<unknown>(
    "POST",
    `/renovation/bank-transactions/${encodeURIComponent(id)}/ignore`,
  );
}

export async function matchBankTransaction(id: string, drawId: string): Promise<void> {
  await mutate<unknown>(
    "POST",
    `/renovation/bank-transactions/${encodeURIComponent(id)}/match`,
    { draw_id: drawId },
  );
}

export function generateDailySnapshot(): Promise<DailySnapshot> {
  return mutate<DailySnapshot>("POST", "/reports/daily-snapshot:generate");
}

// ---------------------------------------------------------------------------
// Knowledge base (M2) — reads for server components, search for the client
// ---------------------------------------------------------------------------

/** GET /v1/kb/documents — newest first. */
export function listKbDocuments(params: KbDocumentListParams = {}): Promise<KbDocument[]> {
  return get<KbDocument[]>("/kb/documents", {
    status: params.status,
    limit: params.limit,
  });
}

export function getKbDocument(id: string): Promise<KbDocumentDetail> {
  return get<KbDocumentDetail>(`/kb/documents/${encodeURIComponent(id)}`);
}

/**
 * GET /v1/kb/search — called from `use client` components (user-interactive
 * search), never during server render.
 */
export function searchKb(params: KbSearchParams): Promise<KbSearchResponse> {
  return get<KbSearchResponse>(
    "/kb/search",
    { q: params.q, mode: params.mode, limit: params.limit },
    SEARCH_TIMEOUT_MS,
  );
}

/**
 * POST /v1/kb/documents (multipart) → 202 with the pending document.
 * Throws ApiError with a display-ready detail (e.g. 413 ไฟล์ใหญ่เกิน 25 MB).
 */
export function uploadKbDocument(payload: KbDocumentUpload): Promise<KbDocument> {
  const form = new FormData();
  form.append("file", payload.file);
  const title = payload.title?.trim();
  if (title) form.append("title", title);
  if (payload.lang) form.append("lang", payload.lang);
  return uploadForm<KbDocument>("/kb/documents", form);
}

// ---------------------------------------------------------------------------
// Competitor intelligence (M3) — reads for server components
// ---------------------------------------------------------------------------

/** GET /v1/competitors/changes — global change feed, newest first. */
export function listCompetitorChanges(
  params: CompetitorChangeListParams = {},
): Promise<CompetitorChange[]> {
  return get<CompetitorChange[]>("/competitors/changes", {
    since: params.since,
    severity: params.severity,
    limit: params.limit,
  });
}

// ---------------------------------------------------------------------------
// Competitor intelligence (M3) — mutations for `use client` components.
// All throw ApiError with a display-ready problem+json detail.
// ---------------------------------------------------------------------------

/**
 * POST /v1/competitors → 201. A 422 ApiError carries the ToS compliance-gate
 * detail (Thai) when a source URL is Facebook/Airbnb/Booking/Agoda — the form
 * renders it as a prominent policy panel, not a generic error.
 */
export function createCompetitor(payload: CompetitorCreate): Promise<Competitor> {
  return mutate<Competitor>("POST", "/competitors", payload);
}

export function updateCompetitor(
  id: string,
  payload: CompetitorPatch,
): Promise<Competitor> {
  return mutate<Competitor>("PATCH", `/competitors/${encodeURIComponent(id)}`, payload);
}

/**
 * POST /v1/competitors/{id}/sources → 201. Same 422 ToS compliance gate as
 * createCompetitor (blocked domains rejected with a Thai detail).
 */
export function createCompetitorSource(
  competitorId: string,
  payload: CompetitorSourceCreate,
): Promise<CompetitorSource> {
  return mutate<CompetitorSource>(
    "POST",
    `/competitors/${encodeURIComponent(competitorId)}/sources`,
    payload,
  );
}

/** DELETE /v1/competitors/{id}/sources/{sourceId} → 204. */
export function deleteCompetitorSource(
  competitorId: string,
  sourceId: string,
): Promise<void> {
  return remove(
    `/competitors/${encodeURIComponent(competitorId)}/sources/${encodeURIComponent(sourceId)}`,
  );
}

/** POST /v1/competitors/{id}:check → 202 { detail }. */
export function checkCompetitor(id: string): Promise<CheckResponse> {
  return mutate<CheckResponse>("POST", `/competitors/${encodeURIComponent(id)}:check`);
}

export function generateWeeklyCompetitorReport(): Promise<WeeklyCompetitorReport> {
  return mutate<WeeklyCompetitorReport>("POST", "/reports/weekly-competitor:generate");
}
