"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";

export function Composer({
  onSubmit,
  onStop,
  isStreaming,
}: {
  onSubmit: (text: string) => Promise<boolean>;
  onStop: () => void;
  isStreaming: boolean;
}) {
  const t = useTranslations("chat");
  const [value, setValue] = useState("");
  const canSend = value.trim().length > 0 && !isStreaming;

  async function submit(): Promise<void> {
    if (!canSend) return;
    const accepted = await onSubmit(value.trim());
    if (accepted) setValue("");
  }

  return (
    <form
      className="mx-auto flex w-full max-w-3xl items-end gap-2"
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
    >
      <textarea
        rows={1}
        value={value}
        disabled={isStreaming}
        aria-label={t("inputPlaceholder")}
        placeholder={t("inputPlaceholder")}
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            void submit();
          }
        }}
        className="min-h-[44px] flex-1 resize-none rounded-md border border-slate-300 px-3 py-2 text-sm disabled:opacity-60"
      />
      {isStreaming ? (
        <button
          type="button"
          onClick={onStop}
          className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700"
        >
          {t("stop")}
        </button>
      ) : (
        <button
          type="submit"
          disabled={!canSend}
          className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {t("send")}
        </button>
      )}
    </form>
  );
}
