"use client";

import { updateCompetitor } from "@/lib/api";
import { useApiAction } from "@/lib/useApiAction";

/**
 * Active on/off switch on a competitor card — PATCH /v1/competitors/{id}.
 * Deactivating asks for confirmation first (the owner loses tracking).
 */
export function CompetitorActiveToggle({
  competitorId,
  active,
  name,
}: {
  competitorId: string;
  active: boolean;
  /** Competitor name for the accessible label and the confirm prompt. */
  name: string;
}) {
  const { run, pending, error } = useApiAction();

  function handleToggle() {
    if (active && !window.confirm(`ปิดติดตาม "${name}" ใช่ไหม? ระบบจะหยุดตรวจแหล่งข้อมูลของรายนี้`)) {
      return;
    }
    void run(() => updateCompetitor(competitorId, { active: !active }));
  }

  return (
    <button
      type="button"
      role="switch"
      aria-checked={active}
      aria-label={`${active ? "ปิดติดตาม" : "เปิดติดตาม"} ${name}`}
      title={error ?? (active ? "กำลังติดตาม — กดเพื่อปิด" : "ปิดติดตามอยู่ — กดเพื่อเปิด")}
      disabled={pending}
      onClick={handleToggle}
      className={`inline-flex h-5 w-9 shrink-0 items-center rounded-full px-0.5 transition-colors disabled:cursor-wait disabled:opacity-60 ${
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
