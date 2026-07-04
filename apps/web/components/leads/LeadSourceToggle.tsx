"use client";

import { patchSource } from "@/lib/api";
import { useApiAction } from "@/lib/useApiAction";

/**
 * Enabled on/off switch on a lead-source card — PATCH /v1/sources/{id}.
 * Disabling asks for confirmation first (the collector stops finding leads
 * from this source).
 */
export function LeadSourceToggle({
  sourceId,
  enabled,
  name,
}: {
  sourceId: string;
  enabled: boolean;
  /** Source name for the accessible label and the confirm prompt. */
  name: string;
}) {
  const { run, pending, error } = useApiAction();

  function handleToggle() {
    if (
      enabled &&
      !window.confirm(`ปิดแหล่งข้อมูล "${name}" ใช่ไหม? ระบบจะหยุดเก็บลีดจากแหล่งนี้`)
    ) {
      return;
    }
    void run(() => patchSource(sourceId, { enabled: !enabled }));
  }

  return (
    <button
      type="button"
      role="switch"
      aria-checked={enabled}
      aria-label={`${enabled ? "ปิด" : "เปิด"}แหล่งข้อมูล ${name}`}
      title={error ?? (enabled ? "เปิดใช้งานอยู่ — กดเพื่อปิด" : "ปิดอยู่ — กดเพื่อเปิด")}
      disabled={pending}
      onClick={handleToggle}
      className={`inline-flex h-5 w-9 shrink-0 items-center rounded-full px-0.5 transition-colors disabled:cursor-wait disabled:opacity-60 ${
        error
          ? "bg-rose-400"
          : enabled
            ? "justify-end bg-blue-600"
            : "justify-start bg-slate-200"
      }`}
    >
      <span className="h-4 w-4 rounded-full bg-white shadow" />
    </button>
  );
}
