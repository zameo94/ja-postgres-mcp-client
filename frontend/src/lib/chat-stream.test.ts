import { afterEach, describe, expect, it, vi } from "vitest";

import { streamChat, type ChatRequestPayload } from "@/lib/chat-stream";

const payload: ChatRequestPayload = {
  messages: [{ role: "user", content: "hi" }],
  provider: "ollama",
};

function sseResponse(chunks: string[]): Response {
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
  return new Response(stream, {
    status: 200,
    headers: { "content-type": "text/event-stream" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("streamChat", () => {
  it("dispatches tokens and completion", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        sseResponse([
          'event: message_start\ndata: {"provider":"ollama","model":"m"}\n\n',
          'event: token\ndata: {"text":"Hel"}\n\n',
          'event: token\ndata: {"text":"lo"}\n\n',
          'event: message_end\ndata: {}\n\n',
        ]),
      ),
    );

    const seen: string[] = [];
    await streamChat(payload, {
      onToken: (text) => seen.push(text),
      onEnd: () => seen.push("END"),
    });

    expect(seen).toEqual(["Hel", "lo", "END"]);
  });

  it("dispatches tool events", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        sseResponse([
          'event: tool_call\ndata: {"id":"c1","name":"db_health","arguments":{}}\n\n',
          'event: tool_result\ndata: {"id":"c1","name":"db_health","content":"ok","is_error":false}\n\n',
          'event: message_end\ndata: {}\n\n',
        ]),
      ),
    );

    const tools: string[] = [];
    await streamChat(payload, {
      onToolCall: (call) => tools.push(`call:${call.name}`),
      onToolResult: (result) => tools.push(`result:${result.name}:${result.isError}`),
    });

    expect(tools).toEqual(["call:db_health", "result:db_health:false"]);
  });

  it("dispatches a server error event", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        sseResponse(['event: error\ndata: {"code":"rate_limited","message":"slow"}\n\n']),
      ),
    );

    const errors: string[] = [];
    await streamChat(payload, { onError: (error) => errors.push(error.code) });

    expect(errors).toEqual(["rate_limited"]);
  });

  it("does not add a stream error after a server error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        sseResponse(['event: error\ndata: {"code":"rate_limited","message":"slow"}\n\n']),
      ),
    );

    const errors: string[] = [];
    await streamChat(payload, { onError: (error) => errors.push(error.code) });

    expect(errors).toEqual(["rate_limited"]);
  });

  it("reports an incomplete stream", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(sseResponse(['event: token\ndata: {"text":"x"}\n\n'])),
    );

    const errors: string[] = [];
    await streamChat(payload, { onError: (error) => errors.push(error.code) });

    expect(errors).toEqual(["stream_incomplete"]);
  });

  it("reports a transport error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("network down")));

    const errors: string[] = [];
    await streamChat(payload, { onError: (error) => errors.push(error.code) });

    expect(errors).toEqual(["network_error"]);
  });

  it("reports malformed events as a protocol error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(sseResponse(["event: token\ndata: {not-json}\n\n"])),
    );

    const errors: string[] = [];
    await streamChat(payload, { onError: (error) => errors.push(error.code) });

    expect(errors).toEqual(["protocol_error"]);
  });

  it("maps a 422 response to a validation error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: [{ msg: "invalid" }] }), {
          status: 422,
          headers: { "content-type": "application/json" },
        }),
      ),
    );

    const errors: string[] = [];
    await streamChat(payload, { onError: (error) => errors.push(error.code) });

    expect(errors).toEqual(["validation_error"]);
  });

  it("maps a JSON error response to its code", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ code: "provider_unavailable", message: "down" }), {
          status: 502,
          headers: { "content-type": "application/json" },
        }),
      ),
    );

    const errors: string[] = [];
    await streamChat(payload, { onError: (error) => errors.push(error.code) });

    expect(errors).toEqual(["provider_unavailable"]);
  });

  it("stays silent when the caller aborts", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(sseResponse(['event: token\ndata: {"text":"x"}\n\n'])),
    );
    const controller = new AbortController();
    controller.abort();

    const errors: string[] = [];
    await streamChat(payload, { onError: (error) => errors.push(error.code) }, controller.signal);

    expect(errors).toEqual([]);
  });
});
