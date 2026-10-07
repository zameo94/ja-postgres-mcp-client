"use client";

import { useTranslations } from "next-intl";

import { Spinner } from "@/components/Spinner";
import type { UiMessage } from "@/lib/types";

export function MessageList({
  messages,
  isStreaming,
}: {
  messages: UiMessage[];
  isStreaming: boolean;
}) {
  const t = useTranslations("chat");

  if (messages.length === 0) {
    return <p className="text-center text-sm text-slate-500">{t("emptyState")}</p>;
  }

  return (
    <ul className="mx-auto flex w-full max-w-3xl flex-col gap-3">
      {messages.map((message, index) => {
        const isLastAssistant = index === messages.length - 1 && message.role === "assistant";
        const running = message.tools.some((tool) => tool.status === "running");
        const failed = message.tools.some((tool) => tool.status === "error");
        const thinking =
          isStreaming && isLastAssistant && message.content === "" && message.tools.length === 0;
        const showStatus = message.tools.length > 0 || thinking;

        return (
          <li
            key={message.id}
            className={`rounded-md px-3 py-2 text-sm ${
              message.role === "user" ? "self-end bg-slate-100" : "self-start bg-white"
            }`}
          >
            {showStatus && (
              <p className="mb-1 flex items-center gap-1.5 text-xs text-slate-500">
                {(running || thinking) && <Spinner />}
                {thinking
                  ? t("thinking")
                  : running
                    ? t("toolRunning")
                    : failed
                      ? t("toolError")
                      : t("toolDone")}
              </p>
            )}
            <p className="whitespace-pre-wrap">{message.content}</p>
          </li>
        );
      })}
    </ul>
  );
}
