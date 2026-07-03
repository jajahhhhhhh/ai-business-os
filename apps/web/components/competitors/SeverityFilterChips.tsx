"use client";

import { useTransition } from "react";
import { usePathname, useRouter } from "next/navigation";
import { SEVERITY_LABELS } from "@/lib/i18n";
import type { ChangeSeverity } from "@/lib/types";

/** Severity chips in urgency order; null = ทั้งหมด (no filter). */
const CHIP_ORDER: ChangeSeverity[] = ["critical", "high", "medium", "low"];

/**
 * Severity filter for the change feed. The page stays server-rendered: chips
 * only push the ?severity= search param and the server re-fetches the feed.
 */
export function SeverityFilterChips({
  selected,
}: {
  /** Currently applied filter from the page's searchParams. */
  selected: ChangeSeverity | null;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const [isPending, startTransition] = useTransition();

  function apply(severity: ChangeSeverity | null) {
    startTransition(() => {
      router.push(severity ? `${pathname}?severity=${severity}` : pathname, {
        scroll: false,
      });
    });
  }

  const chipClass = (active: boolean) =>
    `rounded-full border px-3 py-1 text-xs font-medium transition-colors disabled:opacity-60 ${
      active
        ? "border-blue-200 bg-blue-50 text-blue-700"
        : "border-slate-200 bg-white text-slate-500 hover:bg-slate-50"
    }`;

  return (
    <div
      role="group"
      aria-label="กรองตามระดับความสำคัญ"
      aria-busy={isPending}
      className={`flex flex-wrap items-center gap-2 ${isPending ? "opacity-70" : ""}`.trim()}
    >
      <button
        type="button"
        aria-pressed={selected === null}
        disabled={isPending}
        className={chipClass(selected === null)}
        onClick={() => apply(null)}
      >
        ทั้งหมด
      </button>
      {CHIP_ORDER.map((severity) => (
        <button
          key={severity}
          type="button"
          aria-pressed={selected === severity}
          disabled={isPending}
          className={chipClass(selected === severity)}
          onClick={() => apply(severity)}
        >
          {SEVERITY_LABELS[severity].th}
        </button>
      ))}
    </div>
  );
}
