# `/api/v1/keys` — the new endpoints

Six endpoints, all added by this PR. All require the session cookie; all return
**401** when signed out. Send `credentials: "include"` on every one.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/keys/providers` | The catalogue: providers, models, console links, fallback flag |
| GET | `/api/v1/keys` | This student's keys |
| POST | `/api/v1/keys` | Add a key |
| PATCH | `/api/v1/keys/{id}` | Rename, replace the secret, or promote to default |
| DELETE | `/api/v1/keys/{id}` | Remove a key |
| POST | `/api/v1/keys/{id}/verify` | Re-check a stored key against its provider |

---

## `GET /api/v1/keys/providers` → `200`

Everything the settings page needs to render itself. Call it on mount — do not
hardcode provider names, model lists or console URLs in the frontend.

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
| `key_count` | Includes keys marked `invalid` |
| `has_usable_key` | At least one **active** key. `key_count > 0 && !has_usable_key` is exactly the "all your keys for this provider are broken" state — surface it at the provider level |
| `default_model` (top level) | What a chat request uses when it names no model |
| `system_fallback_enabled` | `true` = a student with no Gemini key can still chat on the project's key. `false` = chat is unavailable until they add one, so gate the chat entry point on it |

---

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

---

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

---

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

---

## `DELETE /api/v1/keys/{credential_id}` → `204`

No body. **404** if the id isn't the caller's.

Confirm first: a deleted key is gone and the student must paste it again. If it
was the default, the server promotes another of that provider's keys, so
**re-fetch the list** rather than removing the row locally.

---

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

---

# The settings screen

Two calls populate it:

```
on mount:
  GET /keys/providers   → the catalogue
  GET /keys             → this student's keys
```

Group by provider from `providers[]`. For each: its `label`, a "Get a key ↗" link
to `console_url`, and that provider's keys from `GET /keys`.

### Adding a key

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

### Empty state

A student with no keys at all: if `system_fallback_enabled` is `true`, say chat
already works on the project's Gemini key and a key of their own is optional
(and required for Claude or GPT). If `false`, adding one is required before chat
works — say that plainly and link the screen from the chat entry point.

### After arriving from a chat 409

Re-fetch `GET /keys`: a key rejected mid-chat is **already** `status: "invalid"`
server-side. Deep-link with the provider preselected and the offending key's
Replace form open.
