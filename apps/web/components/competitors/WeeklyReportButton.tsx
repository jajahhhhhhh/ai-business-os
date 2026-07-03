"use client";

import { useState } from "react";
import { FileText, X } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { FormError } from "@/components/ui/FormError";
import { generateWeeklyCompetitorReport } from "@/lib/api";
import type { WeeklyCompetitorReport } from "@/lib/types";
import { useApiAction } from "@/lib/useApiAction";

/**
 * Header action: generate this week's Thai competitor report and show the
 * body inline — same pattern as the payments DailySnapshotButton.
 */
export function WeeklyReportButton() {
  const { run, pending, error } = useApiAction();
  const [report, setReport] = useState<WeeklyCompetitorReport | null>(null);

  return (
    <div className="relative">
      <Button
        disabled={pending}
        onClick={async () => {
          const result = await run(() => generateWeeklyCompetitorReport());
          if (result) setReport(result);
        }}
      >
        <FileText size={14} />
        {pending ? "กำลังสร้างรายงาน..." : "สร้างรายงานสัปดาห์ตอนนี้"}
      </Button>

      {error && (
        <div className="absolute right-0 top-full z-20 mt-2 w-80 max-w-[90vw]">
          <FormError error={error} />
        </div>
      )}

      {report && (
        <div className="absolute right-0 top-full z-20 mt-2 w-[28rem] max-w-[90vw] rounded-2xl border border-slate-200 bg-white p-4 shadow-lg">
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <p className="text-sm font-semibold text-slate-900">
                รายงานคู่แข่งประจำสัปดาห์
              </p>
              {report.line_sent ? (
                <Badge variant="green">ส่ง LINE แล้ว</Badge>
              ) : (
                <Badge variant="amber">ยังไม่ได้ตั้งค่า LINE</Badge>
              )}
            </div>
            <button
              type="button"
              aria-label="ปิด"
              className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
              onClick={() => setReport(null)}
            >
              <X size={16} />
            </button>
          </div>
          <p className="mt-1 text-xs text-slate-400">ช่วงเวลา {report.period}</p>
          <pre className="mt-3 max-h-80 overflow-y-auto whitespace-pre-wrap rounded-xl bg-slate-50 p-3 font-sans text-xs leading-relaxed text-slate-700">
            {report.body}
          </pre>
        </div>
      )}
    </div>
  );
}
