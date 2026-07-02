/**
 * Typed fetch client for the FastAPI backend (docs/ARCHITECTURE.md §11).
 *
 * Server-component friendly: every call uses `cache: 'no-store'` so pages are
 * always dynamic and never try to reach the API during `next build`.
 * Callers should wrap calls in `safe()` so an unreachable API degrades to an
 * EmptyState instead of crashing the page.
 */

import type {
  AgentRun,
  AgentRunListParams,
  BankAlertIngest,
  BankTransaction,
  BankTransactionListParams,
  Competitor,
  CompetitorChange,
  Contractor,
  ContractorCreate,
  DailySnapshot,
  DrawCreate,
  DrawListParams,
  DrawRow,
  Health,
  Job,
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
} from "./types";

const DEFAULT_BASE_URL = "http://localhost:8000";
const REQUEST_TIMEOUT_MS = 5000;
/** Mutations may hit the LLM (daily snapshot) — allow more headroom than GETs. */
const MUTATION_TIMEOUT_MS = 20000;

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

async function get<T>(path: string, query?: Record<string, QueryValue>): Promise<T> {
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
    signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
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

export function listCompetitors(): Promise<Competitor[]> {
  return get<Competitor[]>("/competitors");
}

export function listCompetitorChanges(
  competitorId: string,
  since?: string,
): Promise<CompetitorChange[]> {
  return get<CompetitorChange[]>(
    `/competitors/${encodeURIComponent(competitorId)}/changes`,
    { since },
  );
}

export async function listAgentRuns(
  params: AgentRunListParams = {},
): Promise<Paginated<AgentRun>> {
  // The M0 backend returns a bare array (`list[AgentRunOut]`); ARCHITECTURE §11
  // reserves the { items, next_cursor } envelope. Normalize so both shapes work.
  const data = await get<AgentRun[] | Paginated<AgentRun>>("/agents/runs", {
    agent: params.agent,
    status: params.status,
  });
  return Array.isArray(data) ? { items: data, next_cursor: null } : data;
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
