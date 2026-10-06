import { parseSseChunk } from "./sse";
import type { ChatError, ChatHistoryMessage, ProviderConfig } from "./types";

export interface ChatRequestPayload {
  messages: ChatHistoryMessage[];
  provider: ProviderConfig;
  temperature?: number;
}

export interface ChatStreamHandlers {
  onStart?: (payload: { provider: string; model: string }) => void;
  onToken?: (text: string) => void;
  onToolCall?: (payload: { id: string; name: string; arguments: Record<string, unknown> }) => void;
  onToolResult?: (payload: {
    id: string;
    name: string;
    content: string;
    isError: boolean;
  }) => void;
  onEnd?: () => void;
  onError?: (error: ChatError) => void;
}

const IDLE_TIMEOUT_MS = 120_000;

/**
 * POST to the chat endpoint (via the Next proxy) and consume the SSE stream.
 * `onError` and `onEnd` are terminal; a caller abort is silent. A period longer
 * than `IDLE_TIMEOUT_MS` without any byte aborts the stream with `stream_timeout`.
 */
export async function streamChat(
  payload: ChatRequestPayload,
  handlers: ChatStreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const controller = new AbortController();
  let timedOut = false;
  let finished = false;
  let idleTimer: ReturnType<typeof setTimeout> | undefined;

  const onCallerAbort = (): void => controller.abort();
  const cleanup = (): void => {
    if (idleTimer !== undefined) clearTimeout(idleTimer);
    signal?.removeEventListener("abort", onCallerAbort);
  };
  const resetIdle = (): void => {
    if (idleTimer !== undefined) clearTimeout(idleTimer);
    idleTimer = setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, IDLE_TIMEOUT_MS);
  };
  const fail = (error: unknown): void => {
    if (finished || signal?.aborted) return;
    if (timedOut) {
      handlers.onError?.({ code: "stream_timeout", message: "The provider stopped responding." });
      return;
    }
    if ((error as Error)?.name === "AbortError") return;
    handlers.onError?.({ code: "network_error", message: "The connection was interrupted." });
  };

  if (signal?.aborted) return;
  signal?.addEventListener("abort", onCallerAbort, { once: true });

  try {
    let response: Response;
    try {
      resetIdle();
      response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        signal: controller.signal,
      });
    } catch (error) {
      fail(error);
      return;
    }

    if (!response.ok) {
      handlers.onError?.(await readError(response));
      return;
    }

    const reader = response.body?.getReader();
    if (!reader) {
      handlers.onError?.({ code: "network_error", message: "The server returned no stream." });
      return;
    }

    const decoder = new TextDecoder();
    let buffer = "";
    const consume = (text: string): void => {
      buffer += text;
      const parsed = parseSseChunk(buffer);
      buffer = parsed.rest;
      for (const event of parsed.events) {
        if (finished) break;
        if (dispatch(event.event, event.data, handlers)) finished = true;
      }
    };

    for (;;) {
      resetIdle();
      const { value, done } = await reader.read();
      if (done) break;
      consume(decoder.decode(value, { stream: true }));
      if (finished) break;
    }

    consume(decoder.decode());
    if (buffer.trim()) consume(`${buffer}\n\n`);

    if (!finished) {
      handlers.onError?.({
        code: "stream_incomplete",
        message: "The connection ended before the answer completed.",
      });
    }
  } catch (error) {
    fail(error);
  } finally {
    cleanup();
  }
}

async function readError(response: Response): Promise<ChatError> {
  try {
    const body = (await response.json()) as {
      code?: unknown;
      message?: unknown;
      detail?: unknown;
    };
    if (typeof body.code === "string") {
      return { code: body.code, message: typeof body.message === "string" ? body.message : response.statusText };
    }
    if (response.status === 422 || "detail" in body) {
      return { code: "validation_error", message: "The request was rejected as invalid." };
    }
  } catch {
    // fall through to the generic error
  }
  if (response.status === 422) {
    return { code: "validation_error", message: "The request was rejected as invalid." };
  }
  return { code: "http_error", message: response.statusText };
}

function dispatch(event: string, rawData: string, handlers: ChatStreamHandlers): boolean {
  let data: Record<string, unknown>;
  try {
    data = JSON.parse(rawData) as Record<string, unknown>;
  } catch {
    handlers.onError?.({ code: "protocol_error", message: "The server sent an invalid event." });
    return true;
  }

  switch (event) {
    case "message_start":
      handlers.onStart?.({
        provider: String(data.provider ?? ""),
        model: String(data.model ?? ""),
      });
      return false;
    case "token":
      handlers.onToken?.(String(data.text ?? ""));
      return false;
    case "tool_call":
      handlers.onToolCall?.({
        id: String(data.id ?? ""),
        name: String(data.name ?? ""),
        arguments: (data.arguments as Record<string, unknown>) ?? {},
      });
      return false;
    case "tool_result":
      handlers.onToolResult?.({
        id: String(data.id ?? ""),
        name: String(data.name ?? ""),
        content: String(data.content ?? ""),
        isError: Boolean(data.is_error),
      });
      return false;
    case "message_end":
      handlers.onEnd?.();
      return true;
    case "error":
      handlers.onError?.({
        code: String(data.code ?? "ERROR"),
        message: String(data.message ?? ""),
      });
      return true;
    default:
      return false;
  }
}
