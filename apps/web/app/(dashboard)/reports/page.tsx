import type { Metadata } from "next";
import { Download, FileText } from "lucide-react";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardHeader } from "@/components/ui/Card";
import { listReports, safe } from "@/lib/api";
import { formatDateTimeTH, formatNumber } from "@/lib/format";
import { REPORT_KIND_LABELS } from "@/lib/i18n";
import type { Report, ReportKind } from "@/lib/types";

export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "รายงาน" };

const KINDS: ReportKind[] = ["daily", "weekly", "monthly"];

function ReportRow({ report }: { report: Report }) {
  return (
    <li className="flex items-center gap-3 px-5 py-3">
      <div className="rounded-xl bg-blue-50 p-2 text-blue-600">
        <FileText size={16} />
      </div>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-slate-800">{report.period}</p>
        <p className="text-xs text-slate-400">
          สร้างเมื่อ {formatDateTimeTH(report.generated_at)}
          {report.sent_at ? ` · ส่งทาง LINE แล้ว ${formatDateTimeTH(report.sent_at)}` : ""}
        </p>
      </div>
      <Badge variant="outline">{report.lang.toUpperCase()}</Badge>
      {report.sent_at ? (
        <Badge variant="green">ส่งแล้ว</Badge>
      ) : (
        <Badge variant="neutral">ยังไม่ส่ง</Badge>
      )}
      {/* Download placeholder — enabled once report files are served from MinIO. */}
      <Button variant="outline" disabled title="การดาวน์โหลดจะเปิดใช้เมื่อเชื่อมต่อที่เก็บไฟล์ (MinIO)">
        <Download size={14} />
        ดาวน์โหลด
      </Button>
    </li>
  );
}

export default async function ReportsPage() {
  const reports = await safe(listReports());

  if (!reports) {
    return (
      <div>
        <PageHeader title="รายงาน" subtitle="คลังรายงานอัตโนมัติภาษาไทย · Reports" />
        <EmptyState />
      </div>
    );
  }

  return (
    <div>
      <PageHeader title="รายงาน" subtitle="คลังรายงานอัตโนมัติภาษาไทย · Reports" />

      <div className="space-y-4">
        {KINDS.map((kind) => {
          const items = reports
            .filter((report) => report.kind === kind)
            .sort((a, b) => b.generated_at.localeCompare(a.generated_at));
          return (
            <Card key={kind}>
              <CardHeader
                title={`รายงาน${REPORT_KIND_LABELS[kind].th}`}
                subtitle={
                  kind === "daily"
                    ? "สรุปสั้นทุกเช้า 07:30 น. · Daily snapshot"
                    : kind === "weekly"
                      ? "สรุปคู่แข่งทุกวันจันทร์ + สรุปปิดสัปดาห์วันศุกร์ · Weekly"
                      : "สรุปปิดเดือนต่อไซต์ · Monthly close"
                }
                action={<Badge variant="blue">{formatNumber(items.length)} ฉบับ</Badge>}
              />
              {items.length === 0 ? (
                <CardContent>
                  <p className="py-3 text-center text-sm text-slate-400">
                    ยังไม่มีรายงาน{REPORT_KIND_LABELS[kind].th}ในคลัง
                  </p>
                </CardContent>
              ) : (
                <ul className="divide-y divide-slate-100">
                  {items.map((report) => (
                    <ReportRow key={report.id} report={report} />
                  ))}
                </ul>
              )}
            </Card>
          );
        })}
      </div>
    </div>
  );
}
