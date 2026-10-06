# AGENTS.md

Guidance for AI coding agents working in `ja-postgres-mcp-client`.

## What this repository is

The browser client for the existing **`ja-postgres-mcp` MCP server**. It is a
small FastAPI + Next.js application: a single chat page that answers questions
against a PostgreSQL database through the MCP tools, plus a settings area to
choose the LLM provider.

This repository owns: the FastAPI backend, the agent that orchestrates
LLM + MCP tool calls, the LLM provider abstraction (local Ollama and external
OpenAI-compatible APIs), the MCP client, the SSE streaming contract, the Next.js
chat UI and its i18n, and client-side provider settings.

This repository does **not** own: the MCP server itself (separate project,
`ja-postgres-mcp`), PostgreSQL access, database tooling, authentication, user
accounts, a CMS, or any server-side persistence.

## Scope for this MVP

- Browser chat with Server-Sent Events (SSE) streaming.
- Stateless FastAPI backend.
- Agent with LLM tool/function calling over the MCP server.
- Two LLM providers: local Ollama and external OpenAI-compatible API.
- Client-side provider settings, with the API key encrypted in the browser.

Explicitly out of scope: PostgreSQL (or any DB) for application persistence,
user accounts, authentication, server-side sessions, conversation history
persistence, CMS/admin, and a Docker container for the MCP server (it runs as a
separate project and is activated by the developer).

## Architecture

```
Browser
  |
  v
Next.js UI (chat + settings)      -- fetch / SSE, same origin
  |
  v  (Next route handler as proxy)
FastAPI (thin HTTP boundary, stateless)
  |
  +--> Agent  (message -> LLM -> tool decision -> MCP -> result -> LLM -> answer)
  |       |
  |       +--> LLMProvider (Ollama | OpenAI-compatible)
  |       +--> MCP client  -->  ja-postgres-mcp server (Streamable HTTP)
  |
  v
PostgreSQL            (reached ONLY through the MCP server)
```

- The MCP server is a **separate deployment**; this repo never starts it and
  never embeds it in a container.
- The browser never talks to the MCP server directly.

## Stack

Backend:

- Python 3.12, Poetry (`package-mode = false`), classic FastAPI layout (`app/...`).
- FastAPI, pydantic-settings, `mcp` client SDK, httpx.
- ruff + mypy (strict), pytest + pytest-asyncio.

Frontend:

- Next.js 15 (App Router), React 19, TypeScript strict.
- next-intl (English only for now), Tailwind CSS.
- Vitest + Testing Library.

## Non-negotiable workflow

1. Work in **small, independent, reviewable steps** (one responsibility per step).
2. For each step: explain the goal, implement only that step, add/update tests.
3. **Do NOT run tests** (`pytest`, `vitest`, runners, integration tests). Write
   them; the developer executes them. A one-off run explicitly requested by the
   developer is an exception, not a policy change.
4. **Do NOT build or run Docker**, and do not start/stop services to verify.
5. Do NOT install dependencies unless strictly required for the current step.
6. After each step, **STOP** and wait for explicit approval before the next step.
7. Never claim tests pass if they were not executed.
8. Keep `README.md` in sync when user-facing behavior changes.

At the end of every task report: what was implemented; files created/modified;
tests written; tests executed (NO); Docker build (NO); architectural notes;
remaining work; risks/assumptions; suggested next branch; suggested commit; a
short summary of the current architecture/state.

## Git rules

- **Never** run `git commit`, `git add`, `git status` or `git push`. The
  developer performs all git operations.
- Branch naming: `feature/<short-name>` (e.g. `feature/project-foundation`),
  matching the sibling server repository. Do **not** use numeric prefixes.
- Integration happens on `dev`; `main` is the release branch.
- Never create tags or releases.

## MCP server integration

- The server is the existing `ja-postgres-mcp` project. It is **not**
  reimplemented here and is **not** containerized here.
- Transport: **MCP Streamable HTTP**; the client uses the `mcp` Python SDK
  (`streamablehttp_client` + `ClientSession`) server-to-server.
- Use the real tool names (`db_health`, `db_list_schemas`, `db_list_tables`,
  `db_describe_table`, `db_list_constraints`, `db_list_relationships`,
  `db_list_indexes`, `db_get_view_definition`, `db_run_read_only_query`,
  `db_preview_table`); never invent tools and never access PostgreSQL directly.
- Discovery tools use opaque **keyset cursors**; the agent must traverse pages
  when it needs complete listings.

## LLM providers

- One abstraction with two adapters: local **Ollama** and external
  **OpenAI-compatible** API. No `if provider == ...` logic spread across the
  codebase: provider-specific details live in the adapters, and a factory builds
  exactly one provider per request.
- The interface covers what the agent actually needs: chat, streaming,
  tool/function calling, configuration validation and normalized errors.
- Provider/model/base URL/API key are supplied by the client **per request**;
  the backend keeps no provider state.
- A **server-side system prompt** (`JA_CLIENT_SYSTEM_PROMPT`, with a built-in
  default) is prepended as a `system` message to every chat turn. It is
  operator-controlled and not user-editable.
- **Canonical streaming contract** is defined in `app/services/llm/base.py`:
  async iterator yielding `TextDelta` and complete `ToolCall` events; errors are
  **raised** as `LLMProviderError`, never yielded; the relative order of text and
  tool calls is **not guaranteed**. The agent consumes this contract only and
  never provider-specific types.
- **Error model** lives in `app/services/llm/errors.py`: stable wire codes
  (`LLMErrorCode`), explicit user-facing messages, and an internal `detail` that
  is never serialized (`to_dict()` exposes `code` + `message` only).
- **SSRF policy** lives in `app/services/llm/url_policy.py`; every user-supplied
  provider base URL must pass through it before reaching `httpx`. The future
  settings/chat endpoint must build the provider through this validation and must
  never hand an arbitrary URL to the client library. DNS-rebinding hardening is
  deferred to that endpoint (see module docstring).

## Agent

- Lives in `app/services/agent/`; drives one turn: messages -> LLM -> complete
  tool calls -> MCP -> tool results -> LLM -> response. Depends only on the LLM
  contract and the MCP client interface (no HTTP/SSE/provider specifics).
- Tool failures are handled at the agent level: an **unknown tool** becomes an
  error result with no MCP round-trip; an **MCP tool-level failure** becomes an
  error result up to `max_tool_failures` per turn, then is re-raised; an **MCP
  connection failure** is fatal. Parallel tool calls are executed **sequentially**
  (deterministic ordering). Tool result content is capped at
  `MAX_TOOL_RESULT_CHARS` with an explicit truncation marker.
- Errors may be raised **mid-stream** (after some deltas), because a tool turn
  calls the model more than once; the SSE layer must handle an error after
  partial output. The caller owns provider/MCP lifecycle (the agent never closes
  them).

## Persistence scope (MVP)

- The server is **stateless**: no PostgreSQL, no users, no auth, no sessions, no
  conversation persistence, no CMS.
- The chat is **in-memory** for the browser session only. Design the agent so
  persistence could be added later without rewriting the core logic, but do
  **not** add a repository/DB abstraction now.
- Cross-turn replay is **text-only**: previous assistant tool calls and tool
  results are not sent back to the model (stateless design). Tracked as a README
  MVP limitation.
- The only persisted state is the user's **provider settings**, stored in the
  browser:
  - provider selection, model, base URL: `localStorage`.
  - API key: **encrypted** with AES-GCM (Web Crypto); ciphertext in
    `localStorage`, a non-exportable `CryptoKey` in IndexedDB; decrypt only when
    sending the credential; **never** plaintext, **never** logged, **never**
    returned by ordinary API responses.
  - If the browser lacks the required crypto/IndexedDB support, fail safely and
    clearly; never fall back to plaintext storage.
- **Documented limitation**: client-side encryption does not protect against XSS
  or malicious same-origin JavaScript. It only avoids plaintext-at-rest and
  accidental exposure through browser storage.

## SSE contract

- Streaming is Server-Sent Events, produced by FastAPI and consumed by the
  browser. The endpoint is a thin transport adapter; business logic lives in the
  agent layer.
- Fixed event model (`ChatEventType`, whose values are the wire names):
  `message_start {provider, model}` once; then `token {text}`,
  `tool_call {id,name,arguments}`, `tool_result {id,name,content,is_error}` as
  they occur; terminal `message_end {}` on success, or `error {code, message}`.
- Semantics: `error` is **terminal** — no `message_end` follows it. A stream that
  ends without a terminal event means the client disconnected. Errors may occur
  **after** partial tokens (a tool turn calls the model more than once).
- Failures are mapped to `{code, message}`: `LLMProviderError`, `AgentError` and
  `MCPError.to_dict()`. Unexpected failures become `internal_error` and are
  logged server-side (never leaked). Expected errors are logged at warning with
  `code` + internal `detail`, never the payload or credentials.
- Handle client disconnects (close the per-request provider), keep the event
  loop unblocked, and never leak internal exceptions or secrets.

## i18n

- UI localization lives in the frontend (`next-intl`). English only for now,
  structured so adding another language is additive.
- The backend does **not** own UI strings: it returns stable machine-readable
  `code`s and language-neutral data; the frontend maps codes to translations.

## Configuration

- Centralized configuration (pydantic-settings on the backend); no scattered
  `os.getenv`. Distinguish application config, provider config, MCP config,
  secrets and development defaults.
- Secrets come from the environment/`.env` (gitignored); never hardcode or
  commit them. A committed `.env.example` documents every variable with
  placeholders.
- Fail clearly and early on missing or invalid required configuration.
- Treat user-supplied external base URLs carefully (avoid an obvious SSRF).

## Error handling and logging

- Distinguish invalid request, invalid provider configuration, LLM provider
  failure, MCP connection failure, MCP tool failure, agent failure, client
  disconnect and unexpected internal error.
- Never expose stack traces or secrets to the browser; keep diagnostics in
  server logs. Never log API keys, authorization headers or raw secrets.

## Testing

- Write deterministic unit/component tests at each boundary: configuration
  validation, provider selection, provider adapters, agent orchestration, MCP
  client behavior, error normalization, SSE event generation, API validation,
  frontend state transitions, frontend SSE handling, settings behavior.
- Fake/mock the boundaries (LLM, MCP). Only a dedicated integration layer may
  use real services.
- Write the tests; the developer runs them. Agents must not execute them.

## Commands

Backend:

```
cd backend
poetry install
poetry run ruff check .
poetry run ruff format --check .
poetry run mypy
# developer-run only:
poetry run pytest
```

Frontend:

```
cd frontend
npm install
npm run lint
npm run typecheck
# developer-run only:
npm test
```

## Project structure

```
backend/
  app/            # FastAPI application (classic layout)
  tests/          # pytest tests
  pyproject.toml
frontend/
  src/
    app/          # Next.js App Router
    components/   # reusable UI primitives
    features/     # feature modules (chat, settings, ...)
    lib/          # transport, api client, state helpers
  messages/       # i18n catalogs (en only for now)
  package.json
README.md
AGENTS.md
```

## Roadmap

Built one step at a time (order may change after each review):

1. Project foundation (repository skeleton + tooling).
2. Centralized configuration and environment handling.
3. FastAPI application boundary and health endpoint.
4. React shell and basic chat page.
5. LLM provider interface.
6. Ollama adapter.
7. External OpenAI-compatible adapter.
8. MCP client.
9. Agent orchestration.
10. SSE contract and backend streaming endpoint.
11. Frontend SSE client and incremental rendering.
12. Options/settings UI.
13. Ollama development setup (documentation only; agents do not build).
14. Security and configuration hardening.
15. Error handling and observability cleanup.
16. Test coverage.
17. Documentation and developer-experience cleanup.

## Versioning

- Semantic Versioning; `0.x` while the MVP evolves.
- The backend version lives in `backend/pyproject.toml`; the frontend version
  lives in `frontend/package.json`.
