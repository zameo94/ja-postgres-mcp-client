"use client";

import { useTranslations } from "next-intl";

import type { UiMessage } from "@/lib/types";

export function MessageList({ messages }: { messages: UiMessage[] }) {
  const t = useTranslations("chat");

  if (messages.length === 0) {
    return <p className="text-center text-sm text-slate-500">{t("emptyState")}</p>;
  }

  return (
    <ul className="mx-auto flex w-full max-w-3xl flex-col gap-3">
      {messages.map((message) => (
        <li
          key={message.id}
          className={`rounded-md px-3 py-2 text-sm ${
            message.role === "user" ? "self-end bg-slate-100" : "self-start bg-white"
          }`}
        >
          {message.tools.length > 0 && (
            <ul className="mb-1 flex flex-wrap gap-1 text-xs text-slate-500">
              {message.tools.map((tool) => (
                <li key={tool.id} className="rounded bg-slate-50 px-2 py-0.5">
                  {tool.status === "running"
                    ? t("toolRunning", { name: tool.name })
                    : tool.status === "error"
                      ? t("toolError", { name: tool.name })
                      : t("toolDone", { name: tool.name })}
                </li>
              ))}
            </ul>
          )}
          <p className="whitespace-pre-wrap">{message.content}</p>
        </li>
      ))}
    </ul>
  );
}
