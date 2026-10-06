import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SecureCryptoUnavailableError } from "@/lib/crypto";
import type { ProviderConfig } from "@/lib/types";

vi.mock("next-intl", () => ({
  useTranslations: () => Object.assign((key: string) => key, { has: () => true }),
}));

vi.mock("@/lib/provider-settings", async () => {
  const actual =
    await vi.importActual<typeof import("@/lib/provider-settings")>("@/lib/provider-settings");
  return {
    isAllowedBaseUrl: actual.isAllowedBaseUrl,
    saveProviderSettings: vi.fn(),
    hasStoredApiKey: vi.fn(() => false),
    saveApiKey: vi.fn(async () => undefined),
    clearApiKey: vi.fn(),
  };
});

import { SettingsPanel } from "@/features/settings/SettingsPanel";
import {
  clearApiKey,
  hasStoredApiKey,
  saveApiKey,
  saveProviderSettings,
} from "@/lib/provider-settings";

const onSubmit = vi.fn();
const onClose = vi.fn();

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(hasStoredApiKey).mockReturnValue(false);
  vi.mocked(saveApiKey).mockResolvedValue(undefined);
});

function renderPanel(initial: ProviderConfig = { provider: "ollama", model: "llama3.1" }) {
  render(<SettingsPanel initial={initial} onSubmit={onSubmit} onClose={onClose} />);
}

describe("SettingsPanel", () => {
  it("saves local (ollama) settings", async () => {
    const user = userEvent.setup();
    renderPanel();

    const modelInput = screen.getByLabelText("model");
    await user.clear(modelInput);
    await user.type(modelInput, "llama3");
    await user.click(screen.getByRole("button", { name: "save" }));

    await waitFor(() =>
      expect(onSubmit).toHaveBeenCalledWith({ provider: "ollama", model: "llama3" }),
    );
    expect(saveProviderSettings).toHaveBeenCalledWith({
      provider: "ollama",
      model: "llama3",
      base_url: "",
    });
  });

  it("requires a model name", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.clear(screen.getByLabelText("model"));
    await user.click(screen.getByRole("button", { name: "save" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("errors.modelRequired");
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("rejects an invalid external base URL", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.selectOptions(screen.getByLabelText("provider"), "external_api");
    await user.click(screen.getByRole("button", { name: "save" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("errors.baseUrlInvalid");
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("requires an API key when none is stored", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.selectOptions(screen.getByLabelText("provider"), "external_api");
    await user.type(screen.getByLabelText("baseUrl"), "https://api.example.com/v1");
    await user.click(screen.getByRole("button", { name: "save" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("errors.apiKeyRequired");
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("encrypts the api key and saves external settings", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.selectOptions(screen.getByLabelText("provider"), "external_api");
    await user.type(screen.getByLabelText("baseUrl"), "https://api.example.com/v1");
    await user.type(screen.getByLabelText("apiKey"), "sk-123");

    await user.click(screen.getByRole("button", { name: "save" }));

    await waitFor(() => expect(saveApiKey).toHaveBeenCalledWith("sk-123"));
    expect(onSubmit).toHaveBeenCalledWith({
      provider: "external_api",
      model: "llama3.1",
      base_url: "https://api.example.com/v1",
    });
  });

  it("fails safely when secure storage is unavailable", async () => {
    vi.mocked(saveApiKey).mockRejectedValueOnce(new SecureCryptoUnavailableError());
    const user = userEvent.setup();
    renderPanel();

    await user.selectOptions(screen.getByLabelText("provider"), "external_api");
    await user.type(screen.getByLabelText("baseUrl"), "https://api.example.com/v1");
    await user.type(screen.getByLabelText("apiKey"), "sk-123");
    await user.click(screen.getByRole("button", { name: "save" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("errors.cryptoUnavailable");
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("clears a stored key", async () => {
    vi.mocked(hasStoredApiKey).mockReturnValue(true);
    const user = userEvent.setup();
    renderPanel({ provider: "external_api", model: "llama3.1", base_url: "https://x.example/v1" });

    await user.click(screen.getByRole("button", { name: "clearKey" }));

    expect(clearApiKey).toHaveBeenCalled();
  });
});
