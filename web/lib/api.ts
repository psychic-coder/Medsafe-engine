import type {
  ApiErrorBody,
  CheckResponse,
  Readiness,
  ResolveResponse,
  SuggestResponse,
} from "./types";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

/**
 * An API failure carrying the engine's own error code where one was returned.
 *
 * The engine never returns a bare 500 body — every non-2xx response is
 * `{ error: { code, message, detail } }` — so the UI can name the actual failure instead of
 * showing "something went wrong".
 */
export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly detail: unknown;

  constructor(message: string, code: string, status: number, detail?: unknown) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
    this.detail = detail;
  }
}

/** A network-level failure: the API is unreachable, or the browser blocked the request. */
export class ApiUnreachableError extends Error {
  constructor(readonly baseUrl: string) {
    super(`Cannot reach the medsafe API at ${baseUrl}`);
    this.name = "ApiUnreachableError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: { "content-type": "application/json", ...init?.headers },
      cache: "no-store",
    });
  } catch {
    // fetch only rejects for network-level problems, which in practice means the API is down or
    // the origin is missing from CORS_ALLOW_ORIGINS. Both need a different fix from an HTTP error.
    throw new ApiUnreachableError(API_BASE_URL);
  }

  if (!response.ok) {
    let body: ApiErrorBody | undefined;
    try {
      body = (await response.json()) as ApiErrorBody;
    } catch {
      body = undefined;
    }
    throw new ApiError(
      body?.error?.message ?? `Request failed with status ${response.status}`,
      body?.error?.code ?? "http_error",
      response.status,
      body?.error?.detail,
    );
  }

  return (await response.json()) as T;
}

export function resolveDrug(
  drug: string,
  includeSubstitutes = true,
): Promise<ResolveResponse> {
  const params = new URLSearchParams({
    drug,
    include_substitutes: String(includeSubstitutes),
  });
  return request<ResolveResponse>(`/resolve?${params.toString()}`);
}

export function checkPrescription(drugs: string[]): Promise<CheckResponse> {
  return request<CheckResponse>("/check", {
    method: "POST",
    body: JSON.stringify({ drugs }),
  });
}

/**
 * Readiness. A 503 here is a real answer, not a failure — it carries the reason the engine is
 * degraded — so it is returned rather than thrown.
 */
export async function fetchReadiness(): Promise<Readiness> {
  try {
    const response = await fetch(`${API_BASE_URL}/health/ready`, {
      cache: "no-store",
    });
    return (await response.json()) as Readiness;
  } catch {
    throw new ApiUnreachableError(API_BASE_URL);
  }
}

/**
 * Type-ahead over names the engine can actually resolve.
 *
 * Failures are swallowed into an empty list on purpose. A suggestion box is an assist, and an
 * error banner because a keystroke's request lost a race would be noise attached to something the
 * user did not ask for. The real search still reports its own failure.
 */
export async function fetchSuggestions(
  query: string,
  signal?: AbortSignal,
): Promise<SuggestResponse> {
  const empty: SuggestResponse = { query, suggestions: [], note: null };
  if (!query.trim()) return empty;
  try {
    const response = await fetch(
      `${API_BASE_URL}/suggest?q=${encodeURIComponent(query)}&limit=8`,
      { cache: "no-store", signal },
    );
    if (!response.ok) return empty;
    return (await response.json()) as SuggestResponse;
  } catch {
    return empty;
  }
}
