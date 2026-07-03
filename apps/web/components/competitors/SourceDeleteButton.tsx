"use client";

import { X } from "lucide-react";
import { deleteCompetitorSource } from "@/lib/api";
import { useApiAction } from "@/lib/useApiAction";

/**
 * Delete icon inside a source chip — confirm, then
 * DELETE /v1/competitors/{id}/sources/{sourceId} (204).
 */
export function SourceDeleteButton({
  competitorId,
  sourceId,
  /** Source host shown in the confirm prompt. */
  label,
}: {
  competitorId: string;
  sourceId: string;
  label: string;
}) {
  const { run, pending, error } = useApiAction();

  function handleDelete() {
    if (!window.confirm(`ลบแหล่งข้อมูล "${label}" ใช่ไหม? ระบบจะหยุดตรวจ URL นี้`)) return;
    void run(() => deleteCompetitorSource(competitorId, sourceId));
  }

  return (
    <button
      type="button"
      aria-label={`ลบแหล่งข้อมูล ${label}`}
      title={error ?? "ลบแหล่งข้อมูลนี้"}
      disabled={pending}
      onClick={handleDelete}
      className={`rounded-full p-0.5 transition-colors disabled:cursor-wait disabled:opacity-50 ${
        error
          ? "text-rose-600 hover:bg-rose-100"
          : "text-slate-400 hover:bg-slate-200 hover:text-slate-600"
      }`}
    >
      <X size={12} />
    </button>
  );
}
