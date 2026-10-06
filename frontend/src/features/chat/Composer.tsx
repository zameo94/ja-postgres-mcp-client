"use client";

import { useTranslations } from "next-intl";

export function Composer() {
  const t = useTranslations("chat");

  return (
    <form
      className="mx-auto flex w-full max-w-3xl items-end gap-2"
      onSubmit={(event) => event.preventDefault()}
    >
      <textarea
        rows={1}
        disabled
        aria-label={t("inputPlaceholder")}
        placeholder={t("inputPlaceholder")}
        className="min-h-[44px] flex-1 resize-none rounded-md border border-slate-300 px-3 py-2 text-sm disabled:opacity-60"
      />
      <button
        type="submit"
        disabled
        className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
      >
        {t("send")}
      </button>
    </form>
  );
}
