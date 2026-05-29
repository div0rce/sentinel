/**
 * Typed API client.
 *
 * Each function maps 1:1 to a backend endpoint. The response interfaces mirror
 * the backend Pydantic shapes — keep them in lockstep when either side changes.
 * The base URL defaults to "" so paths resolve same-origin against the Vite
 * dev-server proxy or the deployed reverse proxy; override with `?api=...` URL
 * parameter or VITE_API_BASE env var if needed.
 */

const DEFAULT_BASE = "";

function getApiBase(): string {
  const url = new URL(window.location.href);
  const override = url.searchParams.get("api");
  if (override) {
    return override.replace(/\/$/, "");
  }
  // Vite injects import.meta.env at build time.
  const fromEnv = (import.meta as { env?: { VITE_API_BASE?: string } }).env?.VITE_API_BASE;
  return (fromEnv ?? DEFAULT_BASE).replace(/\/$/, "");
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {
    Accept: "application/json",
  };
  let payload: BodyInit | undefined;
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  const response = await fetch(`${getApiBase()}${path}`, {
    method,
    headers,
    body: payload,
  });
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const errBody = await response.json();
      if (errBody && typeof errBody === "object" && "detail" in errBody) {
        detail = String(errBody.detail);
      }
    } catch {
      /* response was not JSON; fall back to status */
    }
    throw new ApiError(detail, response.status);
  }
  return (await response.json()) as T;
}

export class ApiError extends Error {
  readonly status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

// --- /query ----------------------------------------------------------------

export interface Citation {
  chunk_id: number;
  document_id: number;
  score: number;
  text: string;
}

export interface QueryRequest {
  query: string;
}

export interface QueryResponse {
  status: "answered" | "refused";
  answer: string;
  citations: Citation[];
  reason: string | null;
}

export function postQuery(body: QueryRequest): Promise<QueryResponse> {
  return request<QueryResponse>("POST", "/query", body);
}

// --- /review ---------------------------------------------------------------

export type WorkflowStatus = "auto_approved" | "needs_review" | "rejected";

export interface ReviewItem {
  id: number;
  extraction_id: number;
  status: WorkflowStatus;
  reason: string | null;
  idempotency_key: string;
  created_at: string;
  updated_at: string;
}

export interface ReviewQueueResponse {
  items: ReviewItem[];
}

export interface ReviewDecisionRequest {
  actor: string;
  note?: string | null;
}

export interface ReviewDecisionResponse {
  id: number;
  extraction_id: number;
  status: "auto_approved" | "rejected";
  audit_event_id: number;
}

export function getReviewQueue(params?: {
  limit?: number;
  offset?: number;
}): Promise<ReviewQueueResponse> {
  const search = new URLSearchParams();
  if (params?.limit !== undefined) search.set("limit", String(params.limit));
  if (params?.offset !== undefined) search.set("offset", String(params.offset));
  const qs = search.toString();
  return request<ReviewQueueResponse>("GET", `/review${qs ? `?${qs}` : ""}`);
}

export function approveReview(
  itemId: number,
  body: ReviewDecisionRequest,
): Promise<ReviewDecisionResponse> {
  return request<ReviewDecisionResponse>("POST", `/review/${itemId}/approve`, body);
}

export function rejectReview(
  itemId: number,
  body: ReviewDecisionRequest,
): Promise<ReviewDecisionResponse> {
  return request<ReviewDecisionResponse>("POST", `/review/${itemId}/reject`, body);
}

// --- /dashboard ------------------------------------------------------------

export interface VolumePoint {
  date: string;
  count: number;
}
export interface VolumeResponse {
  days: number;
  points: VolumePoint[];
}

export interface CategoryPoint {
  schema_name: string;
  count: number;
}
export interface CategoryResponse {
  points: CategoryPoint[];
}

export interface ConfidenceBucket {
  label: string;
  lower: number;
  upper: number;
  count: number;
}
export interface ConfidenceResponse {
  buckets: ConfidenceBucket[];
  total_fields: number;
}

export interface SlaBucket {
  label: string;
  count: number;
}
export interface SlaResponse {
  threshold_hours: number;
  total_needs_review: number;
  over_sla: number;
  buckets: SlaBucket[];
}

export function getVolume(days = 30): Promise<VolumeResponse> {
  return request<VolumeResponse>("GET", `/dashboard/volume?days=${days}`);
}

export function getCategories(): Promise<CategoryResponse> {
  return request<CategoryResponse>("GET", "/dashboard/categories");
}

export function getConfidence(): Promise<ConfidenceResponse> {
  return request<ConfidenceResponse>("GET", "/dashboard/confidence");
}

export function getSla(thresholdHours = 24): Promise<SlaResponse> {
  return request<SlaResponse>("GET", `/dashboard/sla?threshold_hours=${thresholdHours}`);
}
