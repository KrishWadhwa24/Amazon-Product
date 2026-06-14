/**
 * API client helper for the FastAPI backend.
 *
 * - Base URL is configurable via `NEXT_PUBLIC_API_BASE`, defaulting to
 *   `http://localhost:8000`.
 * - All requests use `credentials: "include"` so the signed HTTP-only session
 *   cookie (Requirement 1.4) flows on cross-origin requests. The backend CORS
 *   policy allows the Next.js dev origin with credentials.
 * - Error responses follow the backend shape `{ error: { code, message } }`
 *   and are surfaced as a typed `ApiError`.
 */

export const API_BASE: string =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export interface ApiErrorBody {
  code: string;
  message: string;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, body: ApiErrorBody) {
    super(body.message || `Request failed with status ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.code = body.code || "UNKNOWN";
  }
}

function joinUrl(base: string, path: string): string {
  const trimmedBase = base.replace(/\/+$/, "");
  const trimmedPath = path.startsWith("/") ? path : `/${path}`;
  return `${trimmedBase}${trimmedPath}`;
}

export interface ApiRequestOptions extends Omit<RequestInit, "body"> {
  /** JSON-serializable request body. */
  json?: unknown;
}

/**
 * Perform a credentialed request against the backend and parse the JSON body.
 *
 * Throws {@link ApiError} for non-2xx responses, mapping the backend error
 * envelope when present.
 */
export async function apiFetch<T = unknown>(
  path: string,
  options: ApiRequestOptions = {},
): Promise<T> {
  const { json, headers, ...rest } = options;

  const init: RequestInit = {
    credentials: "include",
    headers: {
      Accept: "application/json",
      ...(json !== undefined ? { "Content-Type": "application/json" } : {}),
      ...headers,
    },
    ...rest,
  };

  if (json !== undefined) {
    init.body = JSON.stringify(json);
  }

  const response = await fetch(joinUrl(API_BASE, path), init);

  // 204 No Content (and empty bodies) parse to undefined.
  const text = await response.text();
  const data: unknown = text ? JSON.parse(text) : undefined;

  if (!response.ok) {
    const envelope = (data as { error?: ApiErrorBody } | undefined)?.error;
    throw new ApiError(
      response.status,
      envelope ?? {
        code: "HTTP_ERROR",
        message: `Request to ${path} failed (${response.status})`,
      },
    );
  }

  return data as T;
}

/** Convenience helpers for common verbs. */
export const api = {
  get: <T = unknown>(path: string, options?: ApiRequestOptions) =>
    apiFetch<T>(path, { ...options, method: "GET" }),
  post: <T = unknown>(path: string, json?: unknown, options?: ApiRequestOptions) =>
    apiFetch<T>(path, { ...options, method: "POST", json }),
  put: <T = unknown>(path: string, json?: unknown, options?: ApiRequestOptions) =>
    apiFetch<T>(path, { ...options, method: "PUT", json }),
  del: <T = unknown>(path: string, options?: ApiRequestOptions) =>
    apiFetch<T>(path, { ...options, method: "DELETE" }),
};
