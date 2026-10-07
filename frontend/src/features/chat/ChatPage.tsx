"use client";

import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";

import { SettingsPanel } from "@/features/settings/SettingsPanel";
import { loadProvider } from "@/lib/provider-settings";
import type { ChatError, ProviderId } from "@/lib/types";

import { Composer } from "./Composer";
import { MessageList } from "./MessageList";
import { useChat } from "./useChat";

// External API is listed first because small local models are weak at MCP tool
// calling. Connection details (base URL, model, API key) are server config.
const DEFAULT_PROVIDER: ProviderId = "external_api";

export function ChatPage() {
  const t = useTranslations("chat");
  const tErrors = useTranslations("errors");
  const [provider, setProvider] = useState<ProviderId>(DEFAULT_PROVIDER);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const { messages, isStreaming, error, send, stop } = useChat(provider);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: "end" });
  }, [messages]);

  useEffect(() => {
    const stored = loadProvider();
    if (stored) setProvider(stored);
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
        <MessageList messages={messages} isStreaming={isStreaming} />
        <div ref={endRef} />
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
