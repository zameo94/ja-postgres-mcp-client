"use client";

import { useTranslations } from "next-intl";

import { Composer } from "./Composer";

export function ChatPage() {
  const t = useTranslations("chat");

  return (
    <div className="flex h-dvh flex-col">
      <header className="flex items-center justify-between border-b border-slate-200 bg-white px-4 py-3">
        <h1 className="text-base font-semibold">{t("title")}</h1>
        <button
          type="button"
          disabled
          className="rounded-md border border-slate-300 px-3 py-1.5 text-sm text-slate-600 disabled:opacity-50"
        >
          {t("openSettings")}
        </button>
      </header>

      <main className="flex flex-1 items-center justify-center p-6">
        <p className="max-w-md text-center text-sm text-slate-500">{t("emptyState")}</p>
      </main>

      <footer className="border-t border-slate-200 bg-white p-4">
        <Composer />
      </footer>
    </div>
  );
}
