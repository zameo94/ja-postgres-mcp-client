import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/chat-stream", () => ({ streamChat: vi.fn() }));

import { useChat } from "@/features/chat/useChat";
import { streamChat } from "@/lib/chat-stream";

const streamMock = vi.mocked(streamChat);

beforeEach(() => {
  vi.clearAllMocks();
});

describe("useChat", () => {
  it("ignores a second send while a turn is in flight", async () => {
    let release!: () => void;
    streamMock.mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          release = resolve;
        }),
    );
    const { result } = renderHook(() => useChat("ollama"));

    let second: boolean | undefined;
    await act(async () => {
      await result.current.send("one");
    });
    await act(async () => {
      second = await result.current.send("two");
    });

    expect(second).toBe(false);
    expect(streamMock).toHaveBeenCalledTimes(1);
    await act(async () => release());
  });

  it("marks running tools as error when the stream fails", async () => {
    streamMock.mockImplementation(async (_payload, handlers) => {
      handlers.onToolCall?.({ id: "c1", name: "db_health", arguments: {} });
      handlers.onError?.({ code: "rate_limited", message: "slow" });
    });
    const { result } = renderHook(() => useChat("ollama"));

    await act(async () => {
      await result.current.send("hi");
    });

    await waitFor(() => expect(result.current.error?.code).toBe("rate_limited"));
    const assistant = result.current.messages.find((message) => message.role === "assistant");
    expect(assistant?.tools[0].status).toBe("error");
  });

  it("aborts the in-flight stream on unmount", async () => {
    let signal: AbortSignal | undefined;
    streamMock.mockImplementation((_payload, _handlers, providedSignal) => {
      signal = providedSignal;
      return new Promise<void>(() => undefined);
    });
    const { result, unmount } = renderHook(() => useChat("ollama"));

    await act(async () => {
      void result.current.send("hi");
    });
    unmount();

    expect(signal?.aborted).toBe(true);
  });
});
