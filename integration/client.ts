/**
 * Reference client for the endpoints this PR adds. Copy it, or read it as the
 * executable version of the spec.
 *
 * The two things that are not optional:
 *   1. `credentials: "include"` on EVERY request — the session is an httpOnly
 *      cookie, so there is no header to set and nothing to read from JS.
 *   2. One place that turns a non-2xx response into an ApiError carrying the
 *      server's `detail`, so callers branch on `status` and show `message`.
 *
 * No dependencies. Framework-agnostic.
 */

import type {
  ChatRequest,
  ContinueSessionOut,
  CreateKeyIn,
  HistoryOut,
  KeyOut,
  ProvidersOut,
  StartSessionOut,
  UpdateKeyIn,
  ValidationErrorItem,
  VerifyKeyOut,
} from "./types";

const BASE_URL: string =
  (import.meta as any).env?.VITE_API_BASE_URL ?? "http://localhost:7777";

/**
 * A failed request. `message` is the server's own `detail`, written to be shown
 * to the student verbatim — render it rather than substituting your own copy.
 */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly body?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** `detail` is a string on our errors and a list on FastAPI validation errors. */
function extractMessage(body: unknown, status: number): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return (detail as ValidationErrorItem[]).map((e) => e.msg).join(", ");
  }
  return `Request failed (${status}).`;
}

/** Called on any 401 — wire this to "clear the user and show login". */
let onUnauthorized: (() => void) | null = null;
export function setUnauthorizedHandler(handler: () => void): void {
  onUnauthorized = handler;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, {
    ...init,
    // Non-negotiable: the session is an httpOnly cookie. Without this the
    // browser neither stores it on login nor sends it on later calls.
    credentials: "include",
    headers: {
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...init.headers,
    },
  });

  if (response.status === 204) return undefined as T;

  const body = await response.json().catch(() => null);

  if (!response.ok) {
    if (response.status === 401) onUnauthorized?.();
    throw new ApiError(response.status, extractMessage(body, response.status), body);
  }
  return body as T;
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined });

// ── Keys — the new endpoints ──────────────────────────────────────────────────

export const keys = {
  /** The catalogue for the settings page. Don't hardcode providers or models. */
  providers: () => request<ProvidersOut>("/api/v1/keys/providers"),

  /** Ordered provider → default-first → oldest. Render grouped, don't re-sort. */
  list: () => request<KeyOut[]>("/api/v1/keys"),

  /**
   * Takes 1–2s: the server verifies the key against the real provider before
   * storing it. Disable the submit button and show a spinner.
   * 201 · 409 duplicate label · 422 rejected/mismatched · 429 (20/hour)
   */
  create: (body: CreateKeyIn) => post<KeyOut>("/api/v1/keys", body),

  /**
   * Rename, replace the secret, or promote to default — send only what changed.
   * Sending `api_key` re-verifies and flips an `invalid` key back to `active`:
   * this is the recovery path from a chat 409.
   * 200 · 404 · 409 · 422 · 429
   */
  update: (id: string, body: UpdateKeyIn) =>
    request<KeyOut>(`/api/v1/keys/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),

  /** 204. If it was the default another is promoted — re-fetch, don't splice. */
  remove: (id: string) => request<void>(`/api/v1/keys/${id}`, { method: "DELETE" }),

  /** Returns 200 even when the key fails — branch on `verified`. 429 at 30/hour. */
  verify: (id: string) => post<VerifyKeyOut>(`/api/v1/keys/${id}/verify`),
};

// ── Chat — unchanged paths, but now authenticated and 409-capable ─────────────

export const chat = {
  /** First message is the raw SOLS paste. Persist the returned session_id. */
  start: (body: ChatRequest) => post<StartSessionOut>("/api/v1/chat", body),

  /** Send ONLY the new message — history lives server-side. */
  send: (sessionId: string, body: ChatRequest) =>
    post<ContinueSessionOut>(`/api/v1/chat/${sessionId}`, body),

  /** Restore a conversation. 404 → clear the stored id and start fresh. */
  history: (sessionId: string) => request<HistoryOut>(`/api/v1/chat/${sessionId}`),
};

// ── Handling the error that matters ───────────────────────────────────────────
//
// A 409 from chat means "no usable key". It is a normal state, not a crash: the
// student cannot continue until they act, so render `error.message` as a
// persistent block with a link to key settings — never a toast that vanishes.
//
//   try {
//     const { reply } = await chat.send(sessionId, { message });
//   } catch (error) {
//     if (!(error instanceof ApiError)) throw error;
//     switch (error.status) {
//       case 409:
//         // error.message names the provider they need. Re-fetch keys on arrival:
//         // a key rejected mid-chat is already `invalid` server-side.
//         return showKeyPrompt(error.message);
//       case 404:
//         return clearSession();               // session gone, or never theirs
//       case 429:
//         return showRetry(error.message);     // provider quota
//       default:
//         return showGenericError();           // 500/502 — don't blame their key
//     }
//   }
