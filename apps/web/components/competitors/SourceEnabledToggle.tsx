"use client";

import { updateSourceEnabled } from "@/lib/api";
import { useApiAction } from "@/lib/useApiAction";

/** Enabled on/off switch for a source row — PATCH /v1/sources/{id}. */
export function SourceEnabledToggle({
  sourceId,
  enabled,
  name,
}: {
  sourceId: string;
  enabled: boolean;
  /** Source name for the accessible label. */
  name: string;
}) {
  const { run, pending, error } = useApiAction();

  return (
    <button
      type="button"
      role="switch"
      aria-checked={enabled}
      aria-label={`${enabled ? "ปิด" : "เปิด"}แหล่งข้อมูล ${name}`}
      title={error ?? (enabled ? "เปิดใช้งานอยู่ — กดเพื่อปิด" : "ปิดอยู่ — กดเพื่อเปิด")}
      disabled={pending}
      onClick={() => run(() => updateSourceEnabled(sourceId, !enabled))}
      className={`inline-flex h-5 w-9 items-center rounded-full px-0.5 transition-colors disabled:cursor-wait disabled:opacity-60 ${
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
