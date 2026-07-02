"use client";

import { Button } from "@/components/ui/Button";
import { FormError } from "@/components/ui/FormError";
import { updateMilestone } from "@/lib/api";
import type { MilestoneStatus } from "@/lib/types";
import { useApiAction } from "@/lib/useApiAction";

/** planned → in_progress → done (delayed can also close straight to done). */
const NEXT: Partial<Record<MilestoneStatus, { status: MilestoneStatus; label: string }>> = {
  planned: { status: "in_progress", label: "เริ่มงาน" },
  in_progress: { status: "done", label: "เสร็จแล้ว" },
  delayed: { status: "done", label: "เสร็จแล้ว" },
};

/** Local YYYY-MM-DD (Asia/Bangkok is UTC+7 — avoid the UTC date rollover). */
function todayLocalISO(): string {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${month}-${day}`;
}

/** Single-step status advance for one milestone row. */
export function MilestoneAdvanceButton({
  milestoneId,
  status,
}: {
  milestoneId: string;
  status: MilestoneStatus;
}) {
  const { run, pending, error } = useApiAction();
  const next = NEXT[status];
  if (!next) return null;

  return (
    <div className="space-y-1 text-right">
      <Button
        variant="outline"
        disabled={pending}
        className="px-3 py-1.5 text-xs"
        onClick={() =>
          run(async () => {
            await updateMilestone(milestoneId, {
              status: next.status,
              // Completing a milestone also records the actual finish date.
              ...(next.status === "done" ? { actual_date: todayLocalISO() } : {}),
            });
            return true;
          })
        }
      >
        {pending ? "กำลังบันทึก..." : next.label}
      </Button>
      <FormError error={error} />
    </div>
  );
}
