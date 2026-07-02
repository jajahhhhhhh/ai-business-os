"use client";

import { useState } from "react";
import { Search } from "lucide-react";
import { t } from "@/lib/i18n";
import type { Locale } from "@/lib/i18n";

export function Topbar({ envLabel }: { envLabel: string }) {
  // Visual-only for now — full locale routing lands with the i18n middleware (M2).
  const [locale, setLocale] = useState<Locale>("th");

  return (
    <header className="sticky top-0 z-10 flex h-16 items-center gap-4 border-b border-slate-200 bg-white/90 px-4 backdrop-blur lg:px-6">
      {/* Search */}
      <div className="relative w-full max-w-md">
        <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
        <input
          type="search"
          placeholder={t("common.searchPlaceholder", locale)}
          aria-label={t("common.searchPlaceholder", locale)}
          className="h-10 w-full rounded-xl border border-slate-200 bg-slate-50 pl-9 pr-3 text-sm text-slate-700 placeholder:text-slate-400 focus:border-blue-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-blue-100"
        />
      </div>

      <div className="ml-auto flex items-center gap-3">
        {/* Locale toggle */}
        <div className="flex items-center rounded-full border border-slate-200 bg-white p-0.5">
          {(["th", "en"] as const).map((code) => (
            <button
              key={code}
              type="button"
              onClick={() => setLocale(code)}
              aria-pressed={locale === code}
              className={`rounded-full px-3 py-1 text-xs font-semibold transition-colors ${
                locale === code
                  ? "bg-blue-600 text-white"
                  : "text-slate-500 hover:text-slate-800"
              }`}
            >
              {code === "th" ? "ไทย" : "EN"}
            </button>
          ))}
        </div>

        {/* Environment badge */}
        <span className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-medium uppercase tracking-wide text-slate-500">
          {envLabel}
        </span>
      </div>
    </header>
  );
}
