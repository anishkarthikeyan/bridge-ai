/**
 * Centralized API client — the only place in the frontend that calls fetch(). Every request
 * goes through the `/api` prefix, which vite.config.ts proxies (prefix stripped) to the real
 * backend in both dev and preview — so the browser only ever talks to one origin (the
 * backend, frozen, has no CORS middleware and never has to change) and the prefix keeps
 * these calls from colliding with the SPA's own `/cases` and `/cases/:id` routes (see
 * vite.config.ts for why the collision is real, not theoretical).
 *
 * Endpoints consumed — all real, all existing, none invented:
 *   GET /health
 *   GET /cases
 *   GET /cases/{id}
 *   GET /cases/{id}/timeline
 *   GET /cases/{id}/decisions
 *   GET /dashboard/summary
 */

const API = "/api";

import type {
  CaseListResponse,
  CaseSnapshot,
  Decision,
  DashboardSummary,
  TimelineEntry,
  Priority,
  ResolutionState,
} from "./types";

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(path: string): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, { headers: { Accept: "application/json" } });
  } catch {
    // Network failure — backend unreachable, dev server down, etc. Never leak the raw
    // fetch/TypeError to the UI; ErrorState only ever shows a plain sentence.
    throw new ApiError("Could not reach the Bridge AI backend.", 0);
  }

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // non-JSON error body — fall back to statusText, never surface raw HTML/stack traces
    }
    throw new ApiError(detail || `Request failed (${response.status})`, response.status);
  }

  return (await response.json()) as T;
}

export interface HealthStatus {
  status: string;
}

export function getHealth(): Promise<HealthStatus> {
  return request<HealthStatus>(`${API}/health`);
}

export interface ListCasesParams {
  status?: ResolutionState;
  priority?: Priority;
  topic?: string;
  limit?: number;
  offset?: number;
}

export function listCases(params: ListCasesParams = {}): Promise<CaseListResponse> {
  const query = new URLSearchParams();
  if (params.status) query.set("status", params.status);
  if (params.priority) query.set("priority", params.priority);
  if (params.topic) query.set("topic", params.topic);
  if (params.limit !== undefined) query.set("limit", String(params.limit));
  if (params.offset !== undefined) query.set("offset", String(params.offset));
  const qs = query.toString();
  return request<CaseListResponse>(`${API}/cases${qs ? `?${qs}` : ""}`);
}

export function getCase(id: string): Promise<CaseSnapshot> {
  return request<CaseSnapshot>(`${API}/cases/${id}`);
}

export function getCaseTimeline(id: string): Promise<TimelineEntry[]> {
  return request<TimelineEntry[]>(`${API}/cases/${id}/timeline`);
}

export function getCaseDecisions(id: string): Promise<Decision[]> {
  return request<Decision[]>(`${API}/cases/${id}/decisions`);
}

export function getDashboardSummary(): Promise<DashboardSummary> {
  return request<DashboardSummary>(`${API}/dashboard/summary`);
}
