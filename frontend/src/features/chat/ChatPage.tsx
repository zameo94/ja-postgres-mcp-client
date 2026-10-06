"use client";

import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { loadProviderSettings, requireApiKey } from "@/lib/provider-settings";
import type { ChatError, ProviderConfig } from "@/lib/types";
import { SettingsPanel } from "@/features/settings/SettingsPanel";

import { Composer } from "./Composer";
import { MessageList } from "./MessageList";
import { useChat } from "./useChat";

const DEFAULT_PROVIDER: ProviderConfig = { provider: "ollama", model: "llama3.1" };

export function ChatPage() {
  const t = useTranslations("chat");
  const tErrors = useTranslations("errors");
  const [provider, setProvider] = useState<ProviderConfig>(DEFAULT_PROVIDER);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const { messages, isStreaming, error, send, stop } = useChat(provider, requireApiKey);

  useEffect(() => {
    const stored = loadProviderSettings();
    if (stored) {
      setProvider({
        provider: stored.provider,
        model: stored.model,
        base_url: stored.base_url || undefined,
      });
    }
  }, []);

  return (
    <div className="flex h-dvh flex-col">
      <header className="flex items-center justify-between border-b border-slate-200 bg-white px-4 py-3">
        <h1 className="text-base font-semibold">{t("title")}</h1>
        <button
          type="button"
          onClick={() => setSettingsOpen(true)}
          className="rounded-md border border-slate-300 px-3 py-1.5 text-sm text-slate-600"
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

      {settingsOpen && (
        <SettingsPanel
          initial={provider}
          onSubmit={setProvider}
          onClose={() => setSettingsOpen(false)}
        />
      )}
    </div>
  );
}

function errorMessage(
  t: { (key: string): string; has: (key: string) => boolean },
  error: ChatError,
): string {
  return t.has(error.code) ? t(error.code) : error.message;
}
