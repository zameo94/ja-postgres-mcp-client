import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("next-intl", () => ({
  useTranslations: () => Object.assign((key: string) => key, { has: () => true }),
}));

import { ChatPage } from "@/features/chat/ChatPage";

describe("ChatPage", () => {
  it("renders the chat shell with title, empty state and composer", () => {
    render(<ChatPage />);

    expect(screen.getByRole("heading", { name: "title" })).toBeInTheDocument();
    expect(screen.getByText("emptyState")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "openSettings" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "send" })).toBeDisabled();
  });
});
