import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next-intl", () => ({
  useTranslations: () => Object.assign((key: string) => key, { has: () => false }),
}));

vi.mock("@/lib/chat-stream", () => ({ streamChat: vi.fn() }));

import { ChatPage } from "@/features/chat/ChatPage";
import { streamChat } from "@/lib/chat-stream";

const streamMock = vi.mocked(streamChat);

beforeEach(() => {
  vi.clearAllMocks();
});

describe("ChatPage", () => {
  it("renders the shell", () => {
    render(<ChatPage />);

    expect(screen.getByRole("heading", { name: "title" })).toBeInTheDocument();
    expect(screen.getByText("emptyState")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "openSettings" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "send" })).toBeDisabled();
  });

  it("streams tokens into the assistant message", async () => {
    streamMock.mockImplementation(async (_payload, handlers) => {
      handlers.onStart?.({ provider: "ollama", model: "m" });
      handlers.onToken?.("Hel");
      handlers.onToken?.("lo");
      handlers.onEnd?.();
    });
    const user = userEvent.setup();
    render(<ChatPage />);

    await user.type(screen.getByPlaceholderText("inputPlaceholder"), "hi");
    await user.click(screen.getByRole("button", { name: "send" }));

    await waitFor(() => expect(screen.getByText("Hello")).toBeInTheDocument());
    expect(screen.getByText("hi")).toBeInTheDocument();
    const [request] = streamMock.mock.calls[0];
    expect(request.messages).toEqual([{ role: "user", content: "hi" }]);
  });

  it("shows tool activity", async () => {
    streamMock.mockImplementation(async (_payload, handlers) => {
      handlers.onToolCall?.({ id: "c1", name: "db_list_tables", arguments: {} });
      handlers.onToolResult?.({ id: "c1", name: "db_list_tables", content: "ok", isError: false });
      handlers.onToken?.("done");
      handlers.onEnd?.();
    });
    const user = userEvent.setup();
    render(<ChatPage />);

    await user.type(screen.getByPlaceholderText("inputPlaceholder"), "tables");
    await user.click(screen.getByRole("button", { name: "send" }));

    await waitFor(() => expect(screen.getByText("done")).toBeInTheDocument());
    expect(screen.getByText("toolDone")).toBeInTheDocument();
  });

  it("shows a stream error via the alert", async () => {
    streamMock.mockImplementation(async (_payload, handlers) => {
      handlers.onError?.({ code: "rate_limited", message: "slow down" });
    });
    const user = userEvent.setup();
    render(<ChatPage />);

    await user.type(screen.getByPlaceholderText("inputPlaceholder"), "hi");
    await user.click(screen.getByRole("button", { name: "send" }));

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("slow down"));
  });

  it("shows a Stop button while streaming", async () => {
    streamMock.mockImplementation(() => new Promise<void>(() => {}));
    const user = userEvent.setup();
    render(<ChatPage />);

    await user.type(screen.getByPlaceholderText("inputPlaceholder"), "hi");
    await user.click(screen.getByRole("button", { name: "send" }));

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "stop" })).toBeInTheDocument(),
    );
  });
});
