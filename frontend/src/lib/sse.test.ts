import { describe, expect, it } from "vitest";

import { parseSseChunk } from "@/lib/sse";

describe("parseSseChunk", () => {
  it("parses a single complete event", () => {
    const { events, rest } = parseSseChunk('event: token\ndata: {"text":"hi"}\n\n');

    expect(events).toEqual([{ event: "token", data: '{"text":"hi"}' }]);
    expect(rest).toBe("");
  });

  it("keeps an incomplete event in the buffer", () => {
    const { events, rest } = parseSseChunk('event: token\ndata: {"text"');

    expect(events).toEqual([]);
    expect(rest).toBe('event: token\ndata: {"text"');
  });

  it("joins multiple data lines of the same event", () => {
    const { events } = parseSseChunk('event: token\ndata: {"a":\ndata: 1}\n\n');

    expect(events).toEqual([{ event: "token", data: '{"a":\n1}' }]);
  });

  it("ignores comment lines", () => {
    const { events } = parseSseChunk(": keep-alive\n\nevent: token\ndata: {}\n\n");

    expect(events).toEqual([{ event: "token", data: "{}" }]);
  });

  it("parses consecutive events in one chunk", () => {
    const { events } = parseSseChunk("event: a\ndata: 1\n\nevent: b\ndata: 2\n\n");

    expect(events.map((event) => event.event)).toEqual(["a", "b"]);
  });

  it("handles CRLF line endings", () => {
    const { events } = parseSseChunk('event: token\r\ndata: {"text":"hi"}\r\n\r\n');

    expect(events).toEqual([{ event: "token", data: '{"text":"hi"}' }]);
  });
});
