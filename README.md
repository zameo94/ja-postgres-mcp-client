# Ja Postgres MCP Client

The code in this repo was entirely written by a coding agent (mostly DeepSeek
V4.1 Flash). The idea, the architecture and the system design were under human
control.

A **browser client** for the separate
[`ja-postgres-mcp`](https://github.com/zameo94/ja-postgres-mcp) MCP server: a
single chat page that answers questions against an existing PostgreSQL database
through the MCP tools, plus a settings area to choose the LLM provider.

The **database is the domain**: tables, columns and data are discovered at
runtime by the MCP server and never hardcoded. The client never accesses
PostgreSQL directly — all data access goes through the server's **read-only**
tools.

> **MVP.** The goal is a solid, verifiable foundation, not a complete platform.
> Some capabilities are intentionally out of scope (see
> [MVP limitations](#mvp-limitations)).

---

## Table of contents

- [Project](#project)
- [Architecture](#architecture)
- [First run](#first-run)
- [Connecting the MCP server](#connecting-the-mcp-server)
- [Chat and SSE](#chat-and-sse)
- [Agent and LLM providers](#agent-and-llm-providers)
- [Security](#security)
- [Technology stack](#technology-stack)
- [Repository layout](#repository-layout)
- [Configuration](#configuration)
- [Tests](#tests)
- [Versioning](#versioning)
- [MVP limitations](#mvp-limitations)
- [License](#license)

---

## Project

`ja-postgres-mcp-client` is a small **FastAPI + Next.js** application exposed in
the browser. The flow is:

```
question -> LLM -> MCP tools -> PostgreSQL (read-only) -> streamed answer
```

What it does:

- **Chat** with Server-Sent Events (SSE) streaming and incremental rendering.
- **Agent** that orchestrates the LLM and the MCP tools (tool/function calling).
- **Two LLM providers**: a local **Ollama** and any external
  **OpenAI-compatible** API.
- **Settings**: the browser only stores the selected provider; the model, base
  URL and API key are server configuration.
- **Schema context**: the backend injects the database relations (and their
  columns) into the system prompt so the model uses schema-qualified names.

What it does **not** do (in this MVP): no authentication, no server-side
persistence (stateless backend), no conversation history storage, no CMS, no
direct database access, and it never starts the MCP server (a separate project).

---

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
- The browser never talks to the MCP server directly, and never holds a server
  secret beyond the user's own provider key.

---

## First run

Requirements:

- **Docker** and Docker Compose (for the containerized stack), or
- **Python 3.12 + Poetry** and **Node.js 20+** (for native development);
- a running **`ja-postgres-mcp` server** (Streamable HTTP);
- an **LLM**: an external OpenAI-compatible API (recommended) and/or a local
  Ollama.

```sh
cp .env.example .env
```

### Client only (Ollama on the host)

```sh
docker compose up -d --build
```

Starts the backend and the frontend. The backend expects a native Ollama on the
host (`host.docker.internal:11434`).

| Service  | URL                          |
| -------- | ---------------------------- |
| Frontend | http://localhost:3000        |
| Backend  | http://localhost:8100/health |

### Client + containerized Ollama

```sh
docker compose -f docker-compose.yaml -f docker-compose.ollama.yaml up -d --build
```

Adds an Ollama container (the backend is repointed to `http://ollama:11434`).
If `OLLAMA_MODEL` is set it is pulled on first startup; otherwise pull manually:

```sh
docker compose -f docker-compose.yaml -f docker-compose.ollama.yaml \
  exec ollama ollama pull <model>
```

### Local development (outside Docker)

```sh
# backend
cd backend
poetry install
poetry run python -m app        # host/port/log level come from JA_CLIENT_* settings

# frontend
cd frontend
npm install
npm run dev                     # http://localhost:3000
```

The frontend proxies `/api/chat` to the backend (`BACKEND_BASE_URL`, default
`http://localhost:8100`).

---

## Connecting the MCP server

The client reaches the MCP server over **MCP Streamable HTTP**.

- Native backend: `JA_CLIENT_MCP_SERVER_URL=http://localhost:8000/mcp`.
- Containerized backend: `http://host.docker.internal:8000/mcp`.
- The server validates the `Host` header, so `host.docker.internal:8000` must be
  in its `JA_POSTGRES_ALLOWED_HOSTS`.

The MCP server is started independently (its own Compose or process); this repo
never runs it.

---

## Chat and SSE

The backend exposes `POST /chat` and streams **Server-Sent Events**; the Next.js
route handler `/api/chat` proxies to it (same origin, no CORS).

Event model (`ChatEventType`):

| Event           | Data                                             |
| --------------- | ------------------------------------------------ |
| `message_start` | `provider`, `model` (once)                       |
| `token`         | `text` (incremental)                             |
| `tool_call`     | `id`, `name`, `arguments`                        |
| `tool_result`   | `id`, `name`, `content`, `is_error`              |
| `message_end`   | — (terminal, on success)                         |
| `error`         | `code`, `message` (terminal)                     |

- `error` is **terminal**: no `message_end` follows it.
- Errors may occur **after** partial tokens (a tool turn calls the model more
  than once).
- A stream that ends without a terminal event means the client disconnected.

The frontend consumes it with `fetch` + `ReadableStream` (not `EventSource`) and
renders tokens incrementally, with a spinner while the model is thinking or
querying.

---

## Agent and LLM providers

- The **agent** drives one turn: `messages -> LLM -> complete tool calls -> MCP
  -> tool results -> LLM -> answer`. It depends only on the provider-neutral LLM
  contract and the MCP client interface.
- **Exactly one provider per request** (no fallback, no multi-provider
  fan-out). The browser only selects the provider; its connection details (base
  URL, model, API key) come from **server configuration**, never from the
  browser.
- Providers (configured via the environment):
  - **External OpenAI-compatible** (recommended for reliable tool calling):
    `JA_CLIENT_EXTERNAL_BASE_URL`, `JA_CLIENT_EXTERNAL_MODEL`,
    `JA_CLIENT_EXTERNAL_API_KEY`.
  - **Local Ollama**: `JA_CLIENT_OLLAMA_BASE_URL`, `JA_CLIENT_OLLAMA_MODEL`.
- **Tool resilience**: an unknown tool returns an error result without an MCP
  round-trip; MCP tool errors are returned to the model (bounded, then
  re-raised); tool result content is capped.
- **Schema context**: the backend injects the schema into the system prompt —
  all relations with columns for small schemas, schemas only for large ones.
  Set `JA_CLIENT_SCHEMA` to pin one schema explicitly.
- **Query errors** from the server surface the PostgreSQL message, so the model
  can correct the query.

---

## Security

- The backend is **stateless**: no database, no user accounts, no sessions.
- Every model-generated SQL statement is treated as **hostile input**; the real
  security boundary is the MCP server (read-only role + `READ ONLY` transaction).
- **SSRF**: a user-supplied external base URL must be `https` (in production),
  and literal or DNS-resolved loopback/private/link-local/metadata addresses are
  rejected.
- **No credential in the browser**: provider connection details (including the
  API key) are **server configuration** (environment). The browser stores only
  the selected provider, so a browser-side XSS cannot exfiltrate the key — it is
  never sent to the client.
- Server logs stay sanitized: no API keys, no request bodies, no DSNs.

---

## Technology stack

- **Backend**: Python 3.12, **FastAPI** + **uvicorn**, the **MCP Python SDK**
  (`mcp` 2.x) as a client, **httpx**, **pydantic-settings**; **ruff** (lint +
  format), **mypy** (type checking), **pytest** + **pytest-asyncio**.
- **Frontend**: **Next.js 15** (App Router), **React 19**, **next-intl** (English
  only for now), **Tailwind CSS**; **Vitest** + Testing Library.
- **Docker** / Docker Compose.

---

## Repository layout

```
backend/
  app/
    main.py          # FastAPI app, lifespan (settings + MCP client), CLI entry point
    api/             # health endpoint + chat SSE endpoint
    core/            # configuration, logging
    schemas/         # request schemas
    services/
      agent/         # tool-calling agent (events, errors)
      llm/           # provider contract, errors, providers, factory, SSE decoder, URL policy
      mcp/           # MCP client (Streamable HTTP) + contract
      chat.py        # chat application service (provider + agent + schema context)
  tests/             # pytest (unit)
  Dockerfile
frontend/
  src/
    app/[locale]/    # Next.js App Router (i18n)
    app/api/chat/    # route handler proxying to the backend
    components/      # reusable UI primitives
    features/chat/   # chat UI, state, SSE client
    features/settings/ # provider settings UI
    lib/             # sse, chat-stream, crypto, settings, types
  messages/          # i18n catalogs (en only for now)
  Dockerfile
docker-compose.yaml        # backend + frontend
docker-compose.ollama.yaml # + Ollama (overlay)
```

---

## Configuration

All backend configuration comes from the environment (with an optional `.env`
fallback). Sensitive values live in a local `.env` (gitignored, copied from
`.env.example`); real environment variables take precedence.

### Application

| Variable                | Default     | Notes                                    |
| ----------------------- | ----------- | ---------------------------------------- |
| `JA_CLIENT_ENVIRONMENT` | `development` | `development` or `production`          |
| `JA_CLIENT_LOG_LEVEL`   | `INFO`      | `DEBUG`/`INFO`/`WARNING`/`ERROR`/`CRITICAL` |
| `JA_CLIENT_HOST`        | `127.0.0.1` | backend bind address                     |
| `JA_CLIENT_PORT`        | `8100`      | backend bind port                        |
| `JA_CLIENT_RELOAD`      | —           | force the uvicorn autoreloader           |

### MCP server

| Variable                        | Default | Notes                    |
| ------------------------------- | ------- | ------------------------ |
| `JA_CLIENT_MCP_SERVER_URL`      | — (required) | Streamable HTTP endpoint |
| `JA_CLIENT_MCP_CONNECT_TIMEOUT` | `10`    | seconds                  |
| `JA_CLIENT_MCP_TOOL_TIMEOUT`    | `30`    | seconds                  |

### LLM

| Variable                    | Default                  | Notes                                    |
| --------------------------- | ------------------------ | ---------------------------------------- |
| `JA_CLIENT_OLLAMA_BASE_URL`   | `http://localhost:11434` | local Ollama base URL                  |
| `JA_CLIENT_OLLAMA_MODEL`      | empty                    | local Ollama model                     |
| `JA_CLIENT_EXTERNAL_BASE_URL` | empty                    | external OpenAI-compatible base URL    |
| `JA_CLIENT_EXTERNAL_MODEL`    | empty                    | external model                         |
| `JA_CLIENT_EXTERNAL_API_KEY`  | empty                    | external API key (secret)              |
| `JA_CLIENT_SYSTEM_PROMPT`     | built-in default         | server-side system prompt              |
| `JA_CLIENT_SCHEMA`            | empty                    | pin the injected schema (empty = discover) |

### Frontend

| Variable            | Default                  | Notes                            |
| ------------------- | ------------------------ | -------------------------------- |
| `BACKEND_BASE_URL`  | `http://localhost:8100`  | backend base URL used by the proxy |

### Docker Compose (host ports)

| Variable           | Default | Notes                                   |
| ------------------ | ------- | --------------------------------------- |
| `BACKEND_PORT`     | `8100`  | published on `127.0.0.1`                |
| `FRONTEND_PORT`    | `3000`  | published on `127.0.0.1`                |
| `OLLAMA_HOST_PORT` | `11435` | Ollama overlay host port                |
| `OLLAMA_MODEL`     | empty   | pulled by the Ollama container if set   |

---

## Tests

Backend:

```sh
cd backend
poetry run pytest
poetry run ruff check .
poetry run ruff format --check .
poetry run mypy            # checks app/ and tests/
```

Frontend:

```sh
cd frontend
npm test                   # vitest
npm run lint
npm run typecheck
```

The backend tests are deterministic and isolated (no real database, MCP server or
LLM); boundaries are faked. Frontend tests use Vitest + Testing Library.

---

## Versioning

The project follows [Semantic Versioning](https://semver.org/) (`MAJOR.MINOR.PATCH`).
It is currently `0.x`: the MCP tool contracts may still change between minor
releases. `1.0.0` will mark those contracts as stable.

The backend version is single-sourced in `backend/pyproject.toml`; the frontend
version lives in `frontend/package.json`.

Releases are tagged `vX.Y.Z` (e.g. `v0.1.0`).

---

## MVP limitations

- **Stateless**: no server-side persistence, no authentication, no sessions.
- **In-memory chat**: the conversation lives in the browser session and is lost
  on reload.
- **Text-only replay**: previous assistant tool calls/results are not sent back
  to the model on later turns.
- **Single provider per request**: no fallback or multi-provider orchestration.
- **Server-side provider config**: the model, base URL and API key are set on the
  server (environment), not per user; the browser only selects the provider.
- **Local small models** may struggle with MCP tool calling; an external
  OpenAI-compatible model is recommended for reliable answers.

---

## License

Released under the [Apache License 2.0](LICENSE).
