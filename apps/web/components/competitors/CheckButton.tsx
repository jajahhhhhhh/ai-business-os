"use client";

import { useEffect, useRef, useState } from "react";
import { Radar } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { FormError } from "@/components/ui/FormError";
import { checkCompetitor } from "@/lib/api";
import { useApiAction } from "@/lib/useApiAction";

/** How long the "ส่งคำสั่งตรวจแล้ว" note stays on screen. */
const NOTICE_MS = 8000;

/**
 * Per-competitor "ตรวจตอนนี้" — POST /v1/competitors/{id}:check (202).
 * Shows a transient accepted note; results land in the change feed once the
 * collector finishes, so the owner refreshes to see them.
 */
export function CheckButton({ competitorId }: { competitorId: string }) {
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
          const result = await run(() => checkCompetitor(competitorId));
          if (result) {
            setNotice("ส่งคำสั่งตรวจแล้ว — รีเฟรชเพื่อดูผล");
            timerRef.current = setTimeout(() => setNotice(null), NOTICE_MS);
          }
        }}
      >
        <Radar size={13} className={pending ? "animate-pulse" : undefined} />
        {pending ? "กำลังส่งคำสั่ง..." : "ตรวจตอนนี้"}
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
