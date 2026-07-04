"use client";

import { useEffect, useRef, useState } from "react";
import { Download } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { FormError } from "@/components/ui/FormError";
import { collectSource } from "@/lib/api";
import { useApiAction } from "@/lib/useApiAction";

/** How long the "ส่งคำสั่งเก็บข้อมูลแล้ว" note stays on screen. */
const NOTICE_MS = 8000;

/**
 * Per-source "เก็บข้อมูลตอนนี้" — POST /v1/sources/{id}:collect (202).
 * Shows a transient accepted note; new leads land on the pipeline board once
 * the collector finishes, so the owner refreshes to see them.
 */
export function LeadSourceCollectButton({ sourceId }: { sourceId: string }) {
  const { run, pending, error } = useApiAction();
  const [notice, setNotice] = useState<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (timerRef.current !== null) clearTimeout(timerRef.current);
    };
  }, []);

  return (
    <div className="space-y-1.5">
      <Button
        variant="outline"
        disabled={pending}
        className="px-3 py-1.5 text-xs"
        onClick={async () => {
          if (timerRef.current !== null) clearTimeout(timerRef.current);
          setNotice(null);
          const result = await run(() => collectSource(sourceId));
          if (result) {
            setNotice("ส่งคำสั่งเก็บข้อมูลแล้ว — รีเฟรชเพื่อดูลีดใหม่");
            timerRef.current = setTimeout(() => setNotice(null), NOTICE_MS);
          }
        }}
      >
        <Download size={13} className={pending ? "animate-pulse" : undefined} />
        {pending ? "กำลังส่งคำสั่ง..." : "เก็บข้อมูลตอนนี้"}
      </Button>
      {notice && (
        <p role="status" className="rounded-xl bg-blue-50 px-3 py-1.5 text-xs text-blue-700">
          {notice}
        </p>
      )}
      <FormError error={error} />
    </div>
  );
}
