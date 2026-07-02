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
  Competitor,
  CompetitorChange,
  Health,
  Job,
  Lead,
  LeadListParams,
  Paginated,
  Report,
  ReportListParams,
  Site,
  SiteSummary,
} from "./types";

const DEFAULT_BASE_URL = "http://localhost:8000";
const REQUEST_TIMEOUT_MS = 5000;

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

export function listAgentRuns(params: AgentRunListParams = {}): Promise<Paginated<AgentRun>> {
  return get<Paginated<AgentRun>>("/agents/runs", {
    agent: params.agent,
    status: params.status,
  });
}

export function listReports(params: ReportListParams = {}): Promise<Report[]> {
  return get<Report[]>("/reports", { kind: params.kind });
}

export function listJobs(): Promise<Job[]> {
  return get<Job[]>("/jobs");
}
