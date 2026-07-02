"use client";

import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { FormError } from "@/components/ui/FormError";
import { payDraw } from "@/lib/api";
import { useApiAction } from "@/lib/useApiAction";

/** "บันทึกจ่ายแล้ว" with an inline confirm step — for pending draw rows. */
export function PayDrawButton({
  drawId,
  confirmText,
}: {
  drawId: string;
  /** e.g. "ยืนยันการจ่าย ฿50,000 ให้ MR.HOME?" — built by the server page. */
  confirmText: string;
}) {
  const { run, pending, error, clearError } = useApiAction();
  const [confirming, setConfirming] = useState(false);

  if (!confirming) {
    return (
      <Button
        variant="outline"
        className="px-3 py-1.5 text-xs"
        onClick={() => {
          clearError();
          setConfirming(true);
        }}
      >
        บันทึกจ่ายแล้ว
      </Button>
    );
  }

  return (
    <div className="space-y-2">
      <p className="text-xs font-medium text-slate-700">{confirmText}</p>
      <div className="flex gap-2">
        <Button
          disabled={pending}
          className="px-3 py-1.5 text-xs"
          onClick={async () => {
            const ok = await run(async () => {
              await payDraw(drawId);
              return true;
            });
            if (ok) setConfirming(false);
          }}
        >
          {pending ? "กำลังบันทึก..." : "ยืนยัน"}
        </Button>
        <Button
          variant="ghost"
          disabled={pending}
          className="px-3 py-1.5 text-xs"
          onClick={() => setConfirming(false)}
        >
          ยกเลิก
        </Button>
      </div>
      <FormError error={error} />
    </div>
  );
}
