# Key vault & model selection — frontend integration

Everything the frontend needs for **bring-your-own-key** and **choosing a model**.
Contracts are transcribed from the routers, Pydantic schemas and the model
registry, not summarised. Live schema on any running instance: `GET /docs`,
`GET /openapi.json` — if this file and the server disagree, the server wins.

**What this covers**

1. Six new endpoints under `/api/v1/keys` — the student's key settings screen.
2. Picking a model on a chat turn, and what happens when no key covers it.
3. The model catalogue, and how a newly released model works without a backend change.

---

## Prerequisites

**Base URL** — one env var (`VITE_API_BASE_URL`), never hardcoded.

| Environment | API base |
|---|---|
| Local | `http://localhost:7777` |
| Render | `https://courseo-backend.onrender.com` |

**Auth** — every endpoint below is behind the session cookie.

- Auth is an httponly `courseo_session` cookie. JavaScript cannot read it: no
  bearer token, no `Authorization` header, nothing in `localStorage`.
- **Every request needs `credentials: "include"`** — including register and login,
  or the browser discards the cookie the response is setting.

  ```ts
  fetch(url, { credentials: "include", ... })   // required on every call
  axios.defaults.withCredentials = true          // axios: set once, globally
  ```

- `GET /api/v1/auth/me` is the only way to test the session. 200 = signed in,
  401 = not. Call it on app boot, and handle 401 once at the client level.

Omitting `credentials: "include"` is the most common failure: login appears to
succeed, then every following call 401s.

**CORS** — the server sends `Access-Control-Allow-Credentials: true` and allows
any origin in the backend's `CORS_ORIGINS` plus **any** `localhost`/`127.0.0.1`
origin on any port, so Vite on 5173, 3000, etc. work in dev with no backend
change. A new **production** frontend URL must be added to `CORS_ORIGINS` on the
backend — a missing origin is a browser-level block you cannot catch in JS.

**Error shape** — always FastAPI's, with `detail` written to be shown to the
student verbatim:

```json
{ "detail": "Add a Google Gemini API key in your settings to use this model." }
```

The exception is **422**, where FastAPI's request validation returns a *list*:

```json
{ "detail": [ { "loc": ["body","api_key"], "msg": "Paste your API key", "type": "value_error" } ] }
```

So the extractor must handle both:

```ts
const message = (d: unknown): string =>
  typeof d === "string" ? d
  : Array.isArray(d) ? d.map((e: any) => e.msg).join(", ")
  : "Something went wrong.";
```

---

## Handling a pasted API key

The one security rule. A key goes in through `POST /keys` or `PATCH /keys/{id}`
and **never comes back out** — no endpoint returns a stored key, and the most any
response reveals is `last4`.

- `<input type="password">`, `autocomplete="off"`
- Clear it from component state the moment the request resolves
- Never log it, never put it in a URL or query string, never keep it in a store
- Don't build a "reveal key" affordance — there is nothing to reveal

---

# 1. The vault: `/api/v1/keys`

Six endpoints. All require the session cookie; all return **401** when signed out.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/keys/providers` | The catalogue: providers, models, console links, fallback flag |
| GET | `/api/v1/keys` | This student's keys |
| POST | `/api/v1/keys` | Add a key |
| PATCH | `/api/v1/keys/{id}` | Rename, replace the secret, or promote to default |
| DELETE | `/api/v1/keys/{id}` | Remove a key |
| POST | `/api/v1/keys/{id}/verify` | Re-check a stored key against its provider |

## `GET /api/v1/keys/providers` → `200`

Everything the settings page and the model picker need to render themselves.
Call it on mount — do not hardcode provider names, model lists or console URLs.

```json
{
  "providers": [
    {
      "provider": "gemini",
      "label": "Google Gemini",
      "console_url": "https://aistudio.google.com/apikey",
      "models": [
        { "name": "gemini-3.5-flash", "label": "Gemini 3.5 Flash", "priced": true },
        { "name": "gemini-2.5-pro",   "label": "Gemini 2.5 Pro",   "priced": false }
      ],
      "default_model": "gemini-3.5-flash",
      "key_count": 1,
      "has_usable_key": true
    },
    {
      "provider": "anthropic",
      "label": "Anthropic Claude",
      "console_url": "https://console.anthropic.com/settings/keys",
      "models": [{ "name": "claude-sonnet-5", "label": "Claude Sonnet 5", "priced": true }],
      "default_model": "claude-sonnet-5",
      "key_count": 0,
      "has_usable_key": false
    },
    {
      "provider": "openai",
      "label": "OpenAI",
      "console_url": "https://platform.openai.com/api-keys",
      "models": [{ "name": "gpt-5.1", "label": "GPT-5.1", "priced": false }],
      "default_model": "gpt-5.1",
      "key_count": 0,
      "has_usable_key": false
    }
  ],
  "default_model": "gemini-3.5-flash",
  "system_fallback_enabled": true
}
```

All three providers are always present, whether or not the student has keys.

| Field | How to use it |
|---|---|
| `console_url` | "Get a key ↗" link — `target="_blank" rel="noopener"` |
| `models[].priced` | `false` = the server has no published rate, so replies on that model return `cost_usd: null`. Show "cost unavailable", never `$0.00` |
| `default_model` (per provider) | What that provider falls back to when a turn names no model |
| `key_count` | Includes keys marked `invalid` |
| `has_usable_key` | At least one **active** key. `key_count > 0 && !has_usable_key` is exactly the "all your keys for this provider are broken" state — surface it at the provider level |
| `default_model` (top level) | What a chat request uses when it names no model |
| `system_fallback_enabled` | `true` = a student with no Gemini key can still chat on the project's key. `false` = chat is unavailable until they add one, so gate the chat entry point on it |

## `GET /api/v1/keys` → `200`

```json
[
  {
    "id": "3f2b...uuid",
    "provider": "gemini",
    "label": "My Gemini key",
    "last4": "ab12",
    "is_default": true,
    "status": "active",
    "created_at": "2026-08-30T04:11:02.881Z",
    "last_used_at": "2026-08-30T05:02:44.010Z",
    "last_verified_at": "2026-08-30T04:11:03.412Z"
  }
]
```

Ordered **provider → default-first → oldest-first**, so you can render grouped by
provider without re-sorting.

`status`:

| Value | Meaning | Row treatment | Actions |
|---|---|---|---|
| `active` | Working as far as we know | Normal | Rename · Make default · Delete |
| `invalid` | The provider rejected it, in chat or on a re-check | Warning + "This key was rejected" | **Replace key** · **Re-check** · Delete |
| `revoked` | Retired server-side | Greyed out | Delete |

Display each key as `••••••••{last4}` with its `label`, and a "Default" badge when
`is_default`.

## `POST /api/v1/keys` → `201`

```json
{ "provider": "gemini", "api_key": "AIza...", "label": "My Gemini key", "make_default": true }
```

| Field | Rules |
|---|---|
| `provider` | Required. `"gemini"` \| `"anthropic"` \| `"openai"` |
| `api_key` | Required. 8–512 chars, trimmed server-side |
| `label` | Optional, ≤100 chars, unique per student per provider. Omit and the server auto-labels (e.g. "Google Gemini key") |
| `make_default` | Optional, defaults to `true`. The first key for a provider becomes default regardless |

Returns a `KeyOut`.

**This request takes 1–2 seconds.** By default the server calls the real provider
to verify the key before saving it, so a typo is caught here rather than three
turns into a conversation. Show a spinner and disable the submit button.

| Status | Cause | UI |
|---|---|---|
| 201 | Saved | Re-fetch both `GET /keys` and `GET /keys/providers` |
| 409 | A key with that label already exists for this provider | Field error on `label` |
| 422 | See below | Show `detail` on the form |
| 429 | More than **20 key changes in an hour** | "Too many changes, try again later" |

The 422 `detail` is already specific and student-facing — render it as-is:

- `"That looks like a Google Gemini key, but you chose OpenAI. Pick the matching provider, or paste the Google Gemini key."` — caught from the key's prefix before any network call
- `"Anthropic Claude rejected this key."`
- `"Could not reach OpenAI to check this key."` — key neither proven nor disproven; offer retry
- `"Unknown provider 'x'. Supported: gemini, anthropic, openai."`

## `PATCH /api/v1/keys/{credential_id}` → `200`

Renames, replaces the secret, or promotes to default. **Every field is optional** —
send only what changed.

```json
{ "api_key": "AIza-new-key", "label": "Renamed", "make_default": true }
```

Returns the updated `KeyOut`. Same status codes as `POST`, plus **404** when the
id isn't the caller's.

Sending `api_key` re-verifies it and flips a previously `invalid` key back to
`active` on success. **This is the recovery path from a chat 409** — make it one
click from the warning row.

## `DELETE /api/v1/keys/{credential_id}` → `204`

No body. **404** if the id isn't the caller's.

Confirm first: a deleted key is gone and the student must paste it again. If it
was the default, the server promotes another of that provider's keys, so
**re-fetch the list** rather than removing the row locally.

## `POST /api/v1/keys/{credential_id}/verify` → `200`

Re-checks a stored key against its provider and updates its `status`. This is the
"Re-check" button next to an `invalid` key.

```json
{ "id": "uuid", "status": "active", "verified": true, "detail": "Google Gemini accepted this key." }
```

**Returns 200 whether or not the key works.** Branch on `verified`, not on the
HTTP status:

```
200 { verified: true,  status: "active",  detail: "Google Gemini accepted this key." } → success
200 { verified: false, status: "invalid", detail: "Google Gemini rejected this key." } → warning + Replace
```

A third case: the provider was unreachable. `verified` is `false` but `status`
stays whatever it was — the key is neither proven nor disproven. The `detail`
says so; don't mark the key bad in your own state, just re-read `status`.

| Status | Cause |
|---|---|
| 200 | Checked — read `verified` |
| 404 | Not the caller's key |
| 429 | More than **30 checks in an hour** |

Never put this on a timer or in a `useEffect` that can re-fire — it makes a real
network call to the provider and is rate limited.

## The key settings screen

Two calls populate it:

```
on mount:
  GET /keys/providers   → the catalogue
  GET /keys             → this student's keys
```

Group by provider from `providers[]`. For each: its `label`, a "Get a key ↗" link
to `console_url`, and that provider's keys from `GET /keys`.

**Adding a key**

```
form: provider (select) · api_key (password input) · label (optional) · make_default (checkbox, on)
                             │
                     POST /keys  ← 1–2s: verifies against the real provider
                             │
        ┌────────────────────┼────────────────┬──────────────┐
      201                  409              422            429
  refresh both         label taken      show `detail`   "too many changes,
     lists            (field error)      on the form     try again later"
```

**Empty state** — a student with no keys at all: if `system_fallback_enabled` is
`true`, say chat already works on the project's Gemini key and a key of their own
is optional (and required for Claude or GPT). If `false`, adding one is required
before chat works — say that plainly and link the screen from the chat entry point.

**Arriving from a chat 409** — re-fetch `GET /keys`: a key rejected mid-chat is
**already** `status: "invalid"` server-side. Deep-link with the provider
preselected and the offending key's Replace form open.

---

# 2. Choosing a model

There is **no dedicated "set model" endpoint**. Selection is one optional field
on the chat request body:

```json
{ "message": "...", "model": "claude-sonnet-5" }
```

Accepted by both `POST /api/v1/chat` (start) and `POST /api/v1/chat/{session_id}`
(continue). It is **sticky**: passing a model mid-conversation switches the
session to it for that turn and every turn after, and `GET /chat/{session_id}`
returns the session's current `model` in `HistoryOut`.

**There is no provider picker.** The provider — and therefore which of the
student's keys is used — is derived from the model *name*, so the model dropdown
is the only selector chat needs.

## How the server resolves a turn to a key

In order:

1. the credential pinned on this chat session (keeps a long conversation on one
   key even after the student changes their default)
2. the student's **default** key for the model's provider
3. any other **active** key they hold for that provider
4. **Implicit provider switch** — only when the request named **no** `model` and
   the student has no key for the default provider: if they hold active keys for
   exactly *one* other provider, the turn silently runs on that provider's
   `default_model` instead of 409-ing. **Read the answering model from the
   response, not from what you assumed** — `MessageOut.model` and
   `MessageOut.provider` are authoritative.
5. the project's own Gemini key — only when `system_fallback_enabled` is `true`
6. otherwise **409**, naming the provider that needs a key

## Can a model be picked with no API key?

The request is always *accepted*; whether it runs depends on the provider:

| Situation | Result |
|---|---|
| Gemini model, no Gemini key, `system_fallback_enabled: true` | **Works** — runs on the project's key. The student never sees a 409 for Gemini |
| Gemini model, no Gemini key, `system_fallback_enabled: false` | **409** |
| Anthropic or OpenAI model, no key for that provider | **409** — there is no fallback for these, ever |
| Model name that maps to no provider | **422** |

So the picker rule is: show a provider's models only when its `has_usable_key`
is `true`, **or** when it's Gemini and `system_fallback_enabled` is `true`. Mark
`priced: false` models as "cost unavailable".

## New error: `409` — no usable key

**The most important thing in this document.** A 409 from either POST chat
endpoint means the student has no usable key for the model's provider. It is a
normal state, not a crash. Four causes, all with an actionable `detail`:

| `detail` says | Cause | Recovery |
|---|---|---|
| `"Add a Google Gemini API key in your settings to use this model."` | No key at all for that provider, and no system fallback covers it | → key settings, provider preselected |
| `"Your Google Gemini key was rejected the last time we used it. Update it in your key settings to keep chatting."` | Every key they hold for that provider is already `invalid` — caught before the turn runs | → key settings, Replace form on that key |
| `"Your Google Gemini key was rejected. Update it in your key settings and try again."` | The provider refused the key **mid-turn**; it has just been marked `invalid` | → key settings, Replace form on that key |
| `"Your … key can no longer be decrypted on this server. Re-enter it in your key settings."` | Server-side master key changed | → key settings, Replace form |

**Render `detail` as a persistent inline block with a "Go to key settings"
button — not a toast.** The student cannot continue until they act on it, so the
message must not disappear. The string names the provider they need; don't
replace it with your own copy.

## Chat response fields tied to the model

`HistoryOut` carries `model` — the model the session currently runs on:

```json
{ "session_id": "uuid", "degree_code": "3778", "model": "gemini-3.5-flash", "messages": [] }
```

On `MessageOut`, `provider` and `cost_usd` were previously always Gemini's. They
are now derived per message from whichever model actually answered:

| Field | Now |
|---|---|
| `provider` | `"gemini"` \| `"anthropic"` \| `"openai"`, or `null` for an unrecognised model — no longer always `"gemini"` |
| `model` | The model that actually answered. **May differ from the one requested** — Google can serve a `gemini-3.5-flash` request as `gemini-3.5-flash-lite` |
| `cost_usd` | **A float or `null`.** `null` means "no published rate for this model" — render "—" or "cost unavailable", never `$0.00` |

One conversation can span providers if the student switches models, so read the
badge from each message's own `provider`, not from the session.

## Chat status codes

| Status | Meaning | UI |
|---|---|---|
| 200 / 201 | Reply | Render it |
| **401** | *(new)* Not signed in — all three chat endpoints now require a session | Global handler → login |
| **404** | *(new)* Session not found **or not theirs** — sessions are now owner-scoped, and any `session_id` cached from before this change is permanently unreadable | Clear the stored `session_id`, start fresh |
| **409** | *(new)* No usable key | The block above — route to key settings |
| 422 | Unknown model name, or the session has no conversation state (stale) | Show `detail`; on a stale session, start a new one |
| 429 | The **provider** is rate limiting that key, or its quota is used up | "Wait and retry, or switch to a key with quota" + retry button |
| **501** | *(new)* That provider's package isn't installed on this server | Rare. "That provider isn't available here" — steer to another |
| 502 | The provider is temporarily unavailable | Offer retry |
| 500 | Our bug | Generic error — do **not** blame the student's key |

---

# 3. The model catalogue

`GET /keys/providers` is the source of truth — **build the picker from it, never
from this table.** Reproduced for reference only, current as of this branch:

| Model `name` | Provider | Label | `priced` |
|---|---|---|---|
| `gemini-3.5-flash` | gemini | Gemini 3.5 Flash | ✅ |
| `gemini-3.5-flash-lite` | gemini | Gemini 3.5 Flash Lite | ❌ |
| `gemini-2.5-flash` | gemini | Gemini 2.5 Flash | ✅ |
| `gemini-2.5-pro` | gemini | Gemini 2.5 Pro | ❌ |
| `gemini-2.0-flash` | gemini | Gemini 2.0 Flash | ✅ |
| `claude-opus-5` | anthropic | Claude Opus 5 | ✅ |
| `claude-sonnet-5` | anthropic | Claude Sonnet 5 | ✅ |
| `claude-haiku-4-5` | anthropic | Claude Haiku 4.5 | ✅ |
| `gpt-5.1` | openai | GPT-5.1 | ❌ |
| `gpt-5.1-mini` | openai | GPT-5.1 mini | ❌ |

Per-provider defaults: `gemini-3.5-flash`, `claude-sonnet-5`, `gpt-5.1`.

**A model released after this list was written still works.** An unregistered
name resolves to a provider by prefix — `gemini*`, `models/gemini*`, `claude*`,
`gpt-*`, `o1*`, `o3*`, `o4*` — so a new model can be sent through `model` before
anyone edits the backend. It just carries no pricing, so replies come back with
`cost_usd: null`. Only a name matching none of those prefixes is a 422.

Consequence for the UI: don't validate model names client-side against the table
above, and always render cost from `cost_usd`, treating `null` as "unavailable".

---

# 4. TypeScript types

Transcribed one-for-one from `app/schemas/vault.py` and `app/schemas/chat.py`.
Anything typed `| null` is genuinely nullable — the backend reports "unknown" as
null rather than guessing.

```ts
// ── Vault ────────────────────────────────────────────────────────────────────
export type Provider = "gemini" | "anthropic" | "openai";

/** `invalid` = the provider rejected it, mid-chat or on a re-check. */
export type CredentialStatus = "active" | "invalid" | "revoked";

export interface CreateKeyIn {
  provider: Provider;
  /** 8–512 chars, trimmed server-side. Never log or persist client-side. */
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
  id: string;                       // uuid
  provider: Provider;
  label: string;
  /** The last four characters — the only part of a key any response reveals. */
  last4: string;
  is_default: boolean;
  status: CredentialStatus;
  created_at: string;               // ISO 8601
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

// ── Chat ─────────────────────────────────────────────────────────────────────
export interface ChatRequest {
  message: string;
  /**
   * Optional. Omit to use the session's model, then the server default.
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
  /** null = no published rate for this model. Render "—", never $0.00. */
  cost_usd: number | null;
}

export interface StartSessionOut { session_id: string; reply: MessageOut; }
export interface ContinueSessionOut { session_id: string; reply: MessageOut; }

export interface HistoryOut {
  session_id: string;
  /** "UNKNOWN" until the student confirms their degree in conversation. */
  degree_code: string;
  /** The model this session currently runs on. */
  model: string | null;
  /** Oldest → newest. `system` messages are already filtered out. */
  messages: MessageOut[];
}

// ── Errors ───────────────────────────────────────────────────────────────────
/** FastAPI's request-validation shape — only ever seen on 422. */
export interface ValidationErrorItem { loc: (string | number)[]; msg: string; type: string; }

/** `detail` is a string on our errors, a list on FastAPI validation errors. */
export interface ApiErrorBody { detail: string | ValidationErrorItem[]; }
```
