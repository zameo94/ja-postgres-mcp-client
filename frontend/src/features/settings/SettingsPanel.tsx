"use client";

import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { saveProvider } from "@/lib/provider-settings";
import type { ProviderId } from "@/lib/types";

export function SettingsPanel({
  initial,
  onSubmit,
  onClose,
}: {
  initial: ProviderId;
  onSubmit: (provider: ProviderId) => void;
  onClose: () => void;
}) {
  const t = useTranslations("settings");
  const [provider, setProvider] = useState<ProviderId>(initial);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent): void {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  function save(): void {
    saveProvider(provider);
    onSubmit(provider);
    onClose();
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
          save();
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

        <p className="text-xs text-slate-500">{t("providerHint")}</p>

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
