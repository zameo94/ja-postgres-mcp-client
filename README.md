# ja-postgres-mcp-client

Browser client for the [`ja-postgres-mcp`](../ja-postgres-mcp) **MCP server**: a
single chat page to ask questions against an existing PostgreSQL database through
the MCP tools, plus a settings area to choose the LLM provider.

The database is never accessed directly: all data access goes through the MCP
server's read-only tools.

> **MVP, work in progress.** Only the project foundation exists so far; the
> backend, agent and UI are built incrementally. See [AGENTS.md](AGENTS.md) for
> the working agreement and roadmap.

## Architecture

```
Browser
  |
  v
Next.js UI (chat + settings)
  |
  v
FastAPI (backend, stateless)
  |
  +--> Agent (LLM orchestration + tool calling)
  |       |
  |       +--> LLM provider (local Ollama | external OpenAI-compatible API)
  |       +--> MCP client  -->  ja-postgres-mcp server (Streamable HTTP)
  |
  v
PostgreSQL            (reached only through the MCP server)
```

## Scope (MVP)

- Browser chat with Server-Sent Events (SSE) streaming.
- Stateless FastAPI backend.
- Agent with LLM tool/function calling over the MCP server.
- Two LLM providers: local **Ollama** and external **OpenAI-compatible** API.
- Client-side provider settings, with the API key encrypted in the browser.

**Out of scope:** server-side persistence, user accounts, authentication,
conversation history, CMS/admin, and a Docker container for the MCP server (it
runs as a separate project).

## Prerequisites

- Python 3.12 and [Poetry](https://python-poetry.org/).
- Node.js 20+ (Next.js 15).
- A running `ja-postgres-mcp` server (Streamable HTTP) to connect to.
- Local Ollama and/or an OpenAI-compatible API endpoint.

## Configuration

The backend reads all configuration from the environment (with an optional
`.env` fallback). Start from the committed example:

```sh
cp .env.example .env
```

Every variable uses the `JA_CLIENT_` prefix; only the MCP server URL is
required.

| Variable                        | Default                     | Notes                          |
| ------------------------------- | --------------------------- | ------------------------------ |
| `JA_CLIENT_ENVIRONMENT`         | `development`               | `development` or `production`  |
| `JA_CLIENT_LOG_LEVEL`           | `INFO`                      |                                |
| `JA_CLIENT_HOST`                | `127.0.0.1`                 | backend bind address           |
| `JA_CLIENT_PORT`                | `8100`                      | backend bind port              |
| `JA_CLIENT_MCP_SERVER_URL`      | — (required)                | Streamable HTTP endpoint       |
| `JA_CLIENT_MCP_CONNECT_TIMEOUT` | `10`                        | seconds                        |
| `JA_CLIENT_MCP_TOOL_TIMEOUT`    | `30`                        | seconds                        |
| `JA_CLIENT_OLLAMA_BASE_URL`     | `http://localhost:11434`    | dev fallback (UI selects it)   |

## MVP limitations

- Chat history is **in-memory** and lost on page reload.
- No authentication: the app is meant to run locally against a trusted MCP
  server.
- The API key is encrypted in the browser; this is **not** a protection against
  XSS or malicious same-origin JavaScript (see [AGENTS.md](AGENTS.md)).

## License

Released under the [Apache License 2.0](LICENSE).
