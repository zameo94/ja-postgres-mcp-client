"use client";

import { useTranslations } from "next-intl";

import type { ChatError, ProviderConfig } from "@/lib/types";

import { Composer } from "./Composer";
import { MessageList } from "./MessageList";
import { useChat } from "./useChat";

// Placeholder until the settings UI (next task) lets the user choose the provider.
const DEFAULT_PROVIDER: ProviderConfig = { provider: "ollama", model: "llama3.1" };

export function ChatPage() {
  const t = useTranslations("chat");
  const tErrors = useTranslations("errors");
  const { messages, isStreaming, error, send, stop } = useChat(DEFAULT_PROVIDER);

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

      {error && (
        <p
          role="alert"
          className="border-b border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700"
        >
          {errorMessage(tErrors, error)}
        </p>
      )}

      <main className="flex-1 overflow-y-auto p-4">
        <MessageList messages={messages} />
      </main>

      <footer className="border-t border-slate-200 bg-white p-4">
        <Composer onSubmit={send} onStop={stop} isStreaming={isStreaming} />
      </footer>
    </div>
  );
}

function errorMessage(
  t: { (key: string): string; has: (key: string) => boolean },
  error: ChatError,
): string {
  return t.has(error.code) ? t(error.code) : error.message;
}
