/**
 * Types for the endpoints this PR adds, plus the fields it adds to chat.
 *
 * Transcribed one-for-one from app/schemas/vault.py and app/schemas/chat.py.
 * Anything typed `| null` is genuinely nullable in a response — the backend
 * reports "unknown" as null rather than guessing a value. Handle it.
 */

// ── Vault (new) ───────────────────────────────────────────────────────────────

export type Provider = "gemini" | "anthropic" | "openai";

/**
 * `invalid` means the provider rejected the key — mid-chat or on a re-check.
 * The student must replace it before that provider works again.
 */
export type CredentialStatus = "active" | "invalid" | "revoked";

export interface CreateKeyIn {
  provider: Provider;
  /** 8–512 chars, trimmed server-side. Never log or persist this client-side. */
  api_key: string;
  /** ≤100 chars, unique per student per provider. Omit to let the server label it. */
  label?: string | null;
  /** Defaults to true. The first key for a provider becomes default regardless. */
  make_default?: boolean;
}

/** Every field optional — send only what changed. */
export interface UpdateKeyIn {
  api_key?: string | null;
  label?: string | null;
  make_default?: boolean | null;
}

export interface KeyOut {
  id: string; // uuid
  provider: Provider;
  label: string;
  /** The last four characters — the only part of a key any response reveals. */
  last4: string;
  is_default: boolean;
  status: CredentialStatus;
  created_at: string; // ISO 8601
  last_used_at: string | null;
  last_verified_at: string | null;
}

export interface ModelOut {
  name: string;
  label: string;
  /** False = no published rate, so replies on it carry cost_usd: null. */
  priced: boolean;
}

export interface ProviderOut {
  provider: Provider;
  label: string;
  /** Where the student issues a key. Link with target="_blank" rel="noopener". */
  console_url: string;
  models: ModelOut[];
  default_model: string;
  /** Includes keys that are `invalid`. */
  key_count: number;
  /** True when at least one key for this provider is `active`. */
  has_usable_key: boolean;
}

export interface ProvidersOut {
  /** Always all three providers, whether or not the student has keys. */
  providers: ProviderOut[];
  /** What a chat request uses when it names no model. */
  default_model: string;
  /** True when a student with no Gemini key can still chat on the project's key. */
  system_fallback_enabled: boolean;
}

export interface VerifyKeyOut {
  id: string;
  status: CredentialStatus;
  /** Branch on this, not the HTTP status — a failed check still returns 200. */
  verified: boolean;
  detail: string;
}

// ── Chat (fields this PR adds) ────────────────────────────────────────────────

export interface ChatRequest {
  message: string;
  /**
   * NEW, optional. Omit to use the session's model, then the server default.
   * The provider — and therefore which key is used — follows from this name.
   */
  model?: string | null;
}

export interface MessageOut {
  id: number | string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
  /** Assistant messages only. No longer always "gemini"; null if unrecognised. */
  provider: Provider | null;
  /** The model that actually answered — may differ from the one requested. */
  model: string | null;
  tokens_in: number | null;
  tokens_out: number | null;
  cached_tokens: number | null;
  /** null means "no published rate for this model". Render "—", never $0.00. */
  cost_usd: number | null;
}

export interface StartSessionOut {
  session_id: string;
  reply: MessageOut;
}

export interface ContinueSessionOut {
  session_id: string;
  reply: MessageOut;
}

export interface HistoryOut {
  session_id: string;
  /** "UNKNOWN" until the student confirms their degree in conversation. */
  degree_code: string;
  /** NEW: the model this session currently runs on. */
  model: string | null;
  /** Oldest → newest. `system` messages are already filtered out. */
  messages: MessageOut[];
}

// ── Errors ────────────────────────────────────────────────────────────────────

/** FastAPI's request-validation shape — only ever seen on 422. */
export interface ValidationErrorItem {
  loc: (string | number)[];
  msg: string;
  type: string;
}

/** `detail` is a string on our errors, a list on FastAPI validation errors. */
export interface ApiErrorBody {
  detail: string | ValidationErrorItem[];
}
