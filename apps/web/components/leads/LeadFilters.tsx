"use client";

import { useState, useTransition } from "react";
import type { FormEvent } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Search } from "lucide-react";
import { Input, Select } from "@/components/ui/Input";
import { LEAD_KIND_LABELS } from "@/lib/i18n";
import type { LeadKind } from "@/lib/types";

const KIND_ORDER: LeadKind[] = ["guest", "longstay", "b2b", "supplier"];

/** Min-score options offered to the owner (API takes any integer). */
export type MinScoreFilter = 50 | 70;

export interface LeadFilterState {
  kind: LeadKind | null;
  minScore: MinScoreFilter | null;
  q: string;
}

/**
 * Filter row above the pipeline board. The page stays server-rendered: the
 * controls only push ?kind=&min_score=&q= search params and the server
 * re-fetches the board — same pattern as the competitors severity chips.
 */
export function LeadFilters({ kind, minScore, q }: LeadFilterState) {
  const router = useRouter();
  const pathname = usePathname();
  const [isPending, startTransition] = useTransition();
  const [query, setQuery] = useState(q);

  function apply(next: LeadFilterState) {
    const params = new URLSearchParams();
    if (next.kind) params.set("kind", next.kind);
    if (next.minScore) params.set("min_score", String(next.minScore));
    const trimmed = next.q.trim();
    if (trimmed !== "") params.set("q", trimmed);
    const search = params.toString();
    startTransition(() => {
      router.push(search ? `${pathname}?${search}` : pathname, { scroll: false });
    });
  }

  function handleMinScoreChange(value: string) {
    // The select only offers "", "50", "70" — validate instead of casting.
    const next: MinScoreFilter | null = value === "50" ? 50 : value === "70" ? 70 : null;
    apply({ kind, minScore: next, q: query });
  }

  function handleSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    apply({ kind, minScore, q: query });
  }

  const chipClass = (active: boolean) =>
    `rounded-full border px-3 py-1 text-xs font-medium transition-colors disabled:opacity-60 ${
      active
        ? "border-blue-200 bg-blue-50 text-blue-700"
        : "border-slate-200 bg-white text-slate-500 hover:bg-slate-50"
    }`;

  return (
    <div
      aria-busy={isPending}
      className={`flex flex-wrap items-center gap-2 ${isPending ? "opacity-70" : ""}`.trim()}
    >
      <div role="group" aria-label="กรองตามประเภทลีด" className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          aria-pressed={kind === null}
          disabled={isPending}
          className={chipClass(kind === null)}
          onClick={() => apply({ kind: null, minScore, q: query })}
        >
          ทั้งหมด
        </button>
        {KIND_ORDER.map((option) => (
          <button
            key={option}
            type="button"
            aria-pressed={kind === option}
            disabled={isPending}
            className={chipClass(kind === option)}
            onClick={() => apply({ kind: option, minScore, q: query })}
          >
            {LEAD_KIND_LABELS[option].th}
          </button>
        ))}
      </div>

      <Select
        aria-label="คะแนนความสนใจขั้นต่ำ"
        value={minScore === null ? "" : String(minScore)}
        disabled={isPending}
        onChange={(event) => handleMinScoreChange(event.target.value)}
        className="px-2 py-1.5 text-xs"
      >
        <option value="">คะแนน: ทั้งหมด</option>
        <option value="50">คะแนน 50+</option>
        <option value="70">คะแนน 70+</option>
      </Select>

      <form onSubmit={handleSearch} className="flex min-w-0 flex-1 items-center gap-2 sm:max-w-xs">
        <Input
          type="search"
          name="q"
          aria-label="ค้นหาลีด"
          value={query}
          disabled={isPending}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="ค้นหาชื่อลีด..."
          className="min-w-0 flex-1 px-3 py-1.5 text-xs"
        />
        <button
          type="submit"
          aria-label="ค้นหา"
          disabled={isPending}
          className="rounded-xl border border-slate-200 bg-white p-2 text-slate-500 transition-colors hover:bg-slate-50 disabled:opacity-60"
        >
          <Search size={13} />
        </button>
      </form>
    </div>
  );
}
