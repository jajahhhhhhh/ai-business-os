"use client";

import { updateCompetitor } from "@/lib/api";
import { useApiAction } from "@/lib/useApiAction";

/** Active on/off switch for a competitor row — PATCH /v1/competitors/{id}. */
export function CompetitorActiveToggle({
  competitorId,
  active,
  name,
}: {
  competitorId: string;
  active: boolean;
  /** Competitor name for the accessible label. */
  name: string;
}) {
  const { run, pending, error } = useApiAction();

  return (
    <button
      type="button"
      role="switch"
      aria-checked={active}
      aria-label={`${active ? "หยุดติดตาม" : "เริ่มติดตาม"} ${name}`}
      title={error ?? (active ? "กำลังติดตาม — กดเพื่อหยุด" : "หยุดติดตามอยู่ — กดเพื่อเริ่ม")}
      disabled={pending}
      onClick={() => run(() => updateCompetitor(competitorId, { active: !active }))}
      className={`inline-flex h-5 w-9 items-center rounded-full px-0.5 transition-colors disabled:cursor-wait disabled:opacity-60 ${
        error
          ? "bg-rose-400"
          : active
            ? "justify-end bg-blue-600"
            : "justify-start bg-slate-200"
      }`}
    >
      <span className="h-4 w-4 rounded-full bg-white shadow" />
    </button>
  );
}
