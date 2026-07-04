"use client";

import { Trash2 } from "lucide-react";
import { deleteSource } from "@/lib/api";
import { useApiAction } from "@/lib/useApiAction";

/**
 * Delete icon on a lead-source card — confirm, then DELETE /v1/sources/{id}
 * (204). Past leads stay in the pipeline; only the collector stops.
 */
export function LeadSourceDeleteButton({
  sourceId,
  /** Source name shown in the confirm prompt. */
  name,
}: {
  sourceId: string;
  name: string;
}) {
  const { run, pending, error } = useApiAction();

  function handleDelete() {
    if (
      !window.confirm(
        `ลบแหล่งข้อมูล "${name}" ใช่ไหม? ลีดที่เก็บมาแล้วยังอยู่ แต่ระบบจะหยุดเก็บเพิ่ม`,
      )
    ) {
      return;
    }
    void run(() => deleteSource(sourceId));
  }

  return (
    <button
      type="button"
      aria-label={`ลบแหล่งข้อมูล ${name}`}
      title={error ?? "ลบแหล่งข้อมูลนี้"}
      disabled={pending}
      onClick={handleDelete}
      className={`rounded-full p-1 transition-colors disabled:cursor-wait disabled:opacity-50 ${
        error
          ? "text-rose-600 hover:bg-rose-100"
          : "text-slate-400 hover:bg-slate-200 hover:text-slate-600"
      }`}
    >
      <Trash2 size={13} />
    </button>
  );
}
