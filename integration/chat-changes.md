# What changed on `/api/v1/chat`

The three chat endpoints keep their paths and response shapes. This PR changes
four things about them. **Read this even if chat already works in your frontend** —
the first two will break an existing integration.

| Method | Path | |
|---|---|---|
| POST | `/api/v1/chat` | start a session → `201` |
| POST | `/api/v1/chat/{session_id}` | continue → `200` |
| GET | `/api/v1/chat/{session_id}` | history → `200` |

---

## 1. Chat now requires a signed-in user  ⚠️ breaking

All three endpoints previously worked with no authentication. They now return
**401** without a valid session cookie.

If your app calls chat before login, it must now register or log in first, and
send `credentials: "include"` on the chat calls too.

## 2. Sessions are owner-scoped  ⚠️ breaking

A `session_id` belonging to another student returns **404** — identical to one
that doesn't exist, so holding a UUID doesn't confirm it exists. This closed a
real hole: `GET /chat/{session_id}` previously returned any conversation to
anyone who had the id.

Consequence for you: **sessions created before this change have no owner and are
permanently unreadable.** Any `session_id` your frontend has cached from before
will 404. Clear stored session ids on upgrade, or just treat the 404 as "start a
new conversation", which you should do anyway.

## 3. Requests can name a model (optional, additive)

```json
{ "message": "...", "model": "claude-sonnet-5" }
```

`model` is optional everywhere. Omit it and the server uses the session's model,
then its own default. **The provider — and therefore which of the student's keys
is used — follows from the model name**, so this is the only selector the UI
needs: there is no separate provider picker in chat.

Passing a different `model` mid-conversation switches the session to it for that
turn and every turn after.

If you offer a picker, build it from `GET /keys/providers`:

- show a provider's models only when its `has_usable_key` is `true` — or when it's
  Gemini and `system_fallback_enabled` is `true`
- mark `priced: false` models as "cost unavailable"

## 4. New response fields (additive)

`HistoryOut` gained `model` — the model the session currently runs on:

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

---

## 5. New error: `409` — no usable key

**The most important thing in this document.** A 409 from either POST endpoint
means the student has no usable key for the model's provider. It is a normal
state, not a crash.

Three causes, all with an actionable `detail`:

| `detail` says | Cause | Recovery |
|---|---|---|
| `"Add a Google Gemini API key in your settings to use this model."` | No key for that provider, and no system fallback covers it | → key settings, provider preselected |
| `"Your Google Gemini key was rejected. Update it in your key settings and try again."` | The provider refused the key mid-turn; it is now `status: "invalid"` | → key settings, Replace form on that key |
| `"Your … key can no longer be decrypted on this server. Re-enter it in your key settings."` | Server-side master key changed | → key settings, Replace form |

**Render `detail` as a persistent inline block with a "Go to key settings"
button — not a toast.** The student cannot continue until they act on it, so the
message must not disappear. The string names the provider they need; don't
replace it with your own copy.

When you land on settings from this error, re-fetch `GET /keys`: a key rejected
mid-chat is already marked `invalid` server-side.

Note the system fallback: when the backend runs with `ALLOW_SYSTEM_FALLBACK_KEY=true`
(the default — check `system_fallback_enabled` from `GET /keys/providers`), a
student with **no Gemini key of their own** still gets a working chat on the
project's key, and never sees this 409 for Gemini. They will see it if they ask
for a Claude or GPT model without a key for it.

---

## Full chat status table

| Status | Meaning | UI |
|---|---|---|
| 200 / 201 | Reply | Render it |
| **401** | *(new)* Not signed in | Global handler → login |
| **404** | Session not found, or not theirs *(now owner-scoped)* | Clear the stored `session_id`, start fresh |
| **409** | *(new)* No usable key | The block above — route to key settings |
| 422 | Unknown model name, or the session has no conversation state (stale) | Show `detail`; on a stale session, start a new one |
| 429 | The **provider** is rate limiting that key, or its quota is used up | "Wait and retry, or switch to a key with quota" + retry button |
| **501** | *(new)* That provider's package isn't installed on this server | Rare. "That provider isn't available here" — steer to another |
| 502 | The provider is temporarily unavailable | Offer retry |
| 500 | Our bug | Generic error — do **not** blame the student's key |

---

## Unchanged

- The first message is still the student's raw SOLS enrolment paste, and the
  server still strips name, student number and contact details before anything
  is stored or sent to the LLM. Say so in the UI — they're pasting a personal record.
- You still send **only the new message** on continue. Conversation state lives
  server-side; never replay history into the request.
- `GET /chat/{session_id}` still returns messages oldest → newest with `system`
  messages already filtered out.
- `degree_code` is still `"UNKNOWN"` until the student confirms their degree in
  conversation — don't render that string raw.
