# Integrating the key vault

Frontend integration doc for the endpoints **this PR adds**: the bring-your-own-key
vault at `/api/v1/keys`. Written to be handed straight to a coding agent — the
contracts are transcribed from the routers and Pydantic schemas, not summarised.

| File | What it is |
|---|---|
| [`keys-api.md`](./keys-api.md) | The six new endpoints, exact shapes and status codes, plus the settings screen to build |
| [`chat-changes.md`](./chat-changes.md) | What changed on the existing `/chat` endpoints because of this — **read this even if chat already works for you** |
| [`types.ts`](./types.ts) | TypeScript types matching the new Pydantic schemas |
| [`client.ts`](./client.ts) | Reference `fetch` client for the new endpoints |

Live schema on any running instance: **`GET /docs`**, **`GET /openapi.json`**. If
this folder and the running server disagree, the server wins.

---

## What this PR adds

Students bring their **own** API key (Google Gemini, Anthropic Claude, OpenAI).
It is stored encrypted and used for that student's chat turns only. Previously
every student ran on one project-wide Gemini key.

Two things for the frontend:

1. **A new key-settings screen** — six new endpoints under `/api/v1/keys`.
2. **A new error state on chat** — `409` meaning "no usable key", with a message
   that has to become a route to that settings screen. See `chat-changes.md`.

Nothing else about `/chat` changes shape, but it now **requires a signed-in user**.

---

## Prerequisite: auth (unchanged by this PR)

`POST /api/v1/auth/register` and `/login` already exist and are untouched here.
Restated only because every new endpoint below is behind them:

- Auth is an **httponly `courseo_session` cookie**. JavaScript cannot read it.
  There is no bearer token, no `Authorization` header, nothing to put in
  `localStorage`.
- **Every request needs `credentials: "include"`** — including register and login,
  or the browser discards the cookie the response is setting.

  ```ts
  fetch(url, { credentials: "include", ... })   // required on every call
  axios.defaults.withCredentials = true          // axios: set once, globally
  ```

- `GET /api/v1/auth/me` is the only way to test the session. 200 = signed in,
  401 = not. Call it on app boot.
- Any endpoint can 401 when the session expires. Handle it once, at the client
  level: clear user state, show login.

Omitting `credentials: "include"` is the most common failure. The symptom is that
login appears to succeed and then every following call 401s.

---

## Base URL and CORS

| Environment | API base |
|---|---|
| Local | `http://localhost:7777` |
| Render | `https://courseo-backend.onrender.com` |

Put it in one env var (`VITE_API_BASE_URL`); never hardcode it.

The server sends `Access-Control-Allow-Credentials: true` and allows any origin
in the backend's `CORS_ORIGINS`, plus **any** `localhost`/`127.0.0.1` origin on
any port — so Vite on 5173, 3000, etc. all work in dev with no backend change.
A new **production** frontend URL must be added to `CORS_ORIGINS` on the backend;
ask before deploying, since a missing origin is a browser-level block you cannot
catch in JS.

---

## Error shape

Every error is FastAPI's:

```json
{ "detail": "Add a Google Gemini API key in your settings to use this model." }
```

`detail` is written to be shown to the student verbatim. Render it.

The exception is **422**, where FastAPI's own request validation returns a *list*:

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

The one security rule for this feature. A key goes in through
`POST /keys` or `PATCH /keys/{id}` and **never comes back out** — no endpoint
returns a stored key, and the most any response reveals is `last4`.

- `<input type="password">`, `autocomplete="off"`
- Clear it from component state the moment the request resolves
- Never log it, never put it in a URL or query string, never keep it in a store
- Don't build a "reveal key" affordance — there is nothing to reveal
