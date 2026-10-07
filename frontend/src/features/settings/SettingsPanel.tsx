"use client";

import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { SecureCryptoUnavailableError } from "@/lib/crypto";
import {
  clearApiKey,
  hasStoredApiKey,
  isAllowedBaseUrl,
  saveApiKey,
  saveProviderSettings,
} from "@/lib/provider-settings";
import type { ProviderConfig, ProviderId } from "@/lib/types";

export function SettingsPanel({
  initial,
  onSubmit,
  onClose,
}: {
  initial: ProviderConfig;
  onSubmit: (config: ProviderConfig) => void;
  onClose: () => void;
}) {
  const t = useTranslations("settings");
  const [provider, setProvider] = useState<ProviderId>(initial.provider);
  const [model, setModel] = useState(initial.model);
  const [baseUrl, setBaseUrl] = useState(initial.base_url ?? "");
  const [apiKey, setApiKey] = useState("");
  const [storedKey, setStoredKey] = useState(hasStoredApiKey());
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent): void {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  useEffect(() => {
    function onStorage(): void {
      setStoredKey(hasStoredApiKey());
    }
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  async function save(): Promise<void> {
    const trimmedModel = model.trim();
    setError(null);
    if (!trimmedModel) {
      setError(t("errors.modelRequired"));
      return;
    }

    try {
      if (provider === "external_api") {
        const url = baseUrl.trim();
        if (!isAllowedBaseUrl(url)) {
          setError(t("errors.baseUrlInvalid"));
          return;
        }
        if (!apiKey.trim() && !storedKey) {
          setError(t("errors.apiKeyRequired"));
          return;
        }
        if (apiKey.trim()) {
          await saveApiKey(apiKey.trim());
          setApiKey("");
          setStoredKey(true);
        }
        saveProviderSettings({ provider: "external_api", model: trimmedModel, base_url: url });
        onSubmit({ provider: "external_api", model: trimmedModel, base_url: url });
      } else {
        saveProviderSettings({ provider: "ollama", model: trimmedModel, base_url: "" });
        onSubmit({ provider: "ollama", model: trimmedModel });
      }
    } catch (cause) {
      setError(
        cause instanceof SecureCryptoUnavailableError
          ? t("errors.cryptoUnavailable")
          : t("errors.generic"),
      );
      return;
    }
    onClose();
  }

  function forgetKey(): void {
    clearApiKey();
    setStoredKey(false);
    setApiKey("");
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={t("title")}
      className="fixed inset-0 flex items-center justify-center bg-slate-900/40 p-4"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <form
        className="w-full max-w-md space-y-4 rounded-lg bg-white p-5"
        onSubmit={(event) => {
          event.preventDefault();
          void save();
        }}
      >
        <h2 className="text-lg font-semibold">{t("title")}</h2>

        <label className="block text-sm">
          <span className="mb-1 block font-medium">{t("provider")}</span>
          <select
            aria-label={t("provider")}
            autoFocus
            value={provider}
            onChange={(event) => setProvider(event.target.value as ProviderId)}
            className="w-full rounded-md border border-slate-300 px-3 py-2"
          >
            <option value="external_api">{t("providerExternal")}</option>
            <option value="ollama">{t("providerOllama")}</option>
          </select>
        </label>

        <label className="block text-sm">
          <span className="mb-1 block font-medium">{t("model")}</span>
          <input
            aria-label={t("model")}
            value={model}
            onChange={(event) => setModel(event.target.value)}
            className="w-full rounded-md border border-slate-300 px-3 py-2"
          />
        </label>

        {provider === "external_api" && (
          <>
            <label className="block text-sm">
              <span className="mb-1 block font-medium">{t("baseUrl")}</span>
              <input
                aria-label={t("baseUrl")}
                value={baseUrl}
                onChange={(event) => setBaseUrl(event.target.value)}
                placeholder="https://api.example.com/v1"
                className="w-full rounded-md border border-slate-300 px-3 py-2"
              />
            </label>

            <label className="block text-sm">
              <span className="mb-1 block font-medium">{t("apiKey")}</span>
              <input
                aria-label={t("apiKey")}
                type="password"
                autoComplete="new-password"
                value={storedKey ? "••••••••••••" : apiKey}
                disabled={storedKey}
                onChange={(event) => setApiKey(event.target.value)}
                className="w-full rounded-md border border-slate-300 px-3 py-2 disabled:bg-slate-100 disabled:text-slate-500"
              />
            </label>

            {storedKey && (
              <div className="flex items-center justify-between text-xs text-slate-500">
                <span>{t("apiKeyStored")}</span>
                <button type="button" onClick={forgetKey} className="underline">
                  {t("clearKey")}
                </button>
              </div>
            )}
          </>
        )}

        {error && (
          <p role="alert" className="text-sm text-red-600">
            {error}
          </p>
        )}

        <div className="flex justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-slate-300 px-4 py-2 text-sm"
          >
            {t("cancel")}
          </button>
          <button
            type="submit"
            className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white"
          >
            {t("save")}
          </button>
        </div>
      </form>
    </div>
  );
}
