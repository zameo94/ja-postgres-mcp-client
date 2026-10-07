import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next-intl", () => ({
  useTranslations: () => Object.assign((key: string) => key, { has: () => true }),
}));

vi.mock("@/lib/provider-settings", () => ({ saveProvider: vi.fn() }));

import { SettingsPanel } from "@/features/settings/SettingsPanel";
import { saveProvider } from "@/lib/provider-settings";

const onSubmit = vi.fn();
const onClose = vi.fn();

beforeEach(() => {
  vi.clearAllMocks();
});

describe("SettingsPanel", () => {
  it("saves the selected provider", async () => {
    const user = userEvent.setup();
    render(<SettingsPanel initial="external_api" onSubmit={onSubmit} onClose={onClose} />);

    await user.selectOptions(screen.getByLabelText("provider"), "ollama");
    await user.click(screen.getByRole("button", { name: "save" }));

    expect(saveProvider).toHaveBeenCalledWith("ollama");
    expect(onSubmit).toHaveBeenCalledWith("ollama");
    expect(onClose).toHaveBeenCalled();
  });
});
