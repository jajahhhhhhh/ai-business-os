import type { Metadata } from "next";
import Link from "next/link";
import { CalendarClock, ShieldCheck } from "lucide-react";
import { DataTable } from "@/components/DataTable";
import type { Column } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/Badge";
import type { BadgeVariant } from "@/components/ui/Badge";
import { Card, CardContent, CardHeader } from "@/components/ui/Card";
import { listCompetitors, listJobs, safe } from "@/lib/api";
import { formatDateTimeTH } from "@/lib/format";
import { SOURCE_TYPE_LABELS, sourceStatusLabel } from "@/lib/i18n";
import type { CompetitorSource, Job } from "@/lib/types";

export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "ตั้งค่า" };

/** Badge tone from the collector's last_status (free string, never crashes). */
function sourceStatusBadge(status: string): BadgeVariant {
  const slug = status.toLowerCase();
  if (slug === "changed") return "blue";
  if (slug === "error" || slug === "blocked" || slug === "refused") return "red";
  if (slug === "ok") return "green";
  // baseline / unchanged / unknown values stay neutral.
  return "neutral";
}

/** Competitor source flattened with its owner's name for the registry table. */
interface SourceRow {
  competitorName: string;
  source: CompetitorSource;
}

/**
 * Live sources registry flattened from GET /v1/competitors — read-only here;
 * management (add/delete) lives on the competitors page. Every row shown
 * already passed the ToS compliance gate at creation time, hence the ✅.
 */
const SOURCE_COLUMNS: Column<SourceRow>[] = [
  {
    key: "url",
    header: "แหล่งข้อมูล",
    render: ({ competitorName, source }) => (
      <div className="min-w-0 max-w-[18rem]">
        <p className="truncate font-medium text-slate-900">{competitorName}</p>
        <p className="mt-0.5 truncate text-xs text-slate-400" title={source.url}>
          {source.url}
        </p>
      </div>
    ),
  },
  {
    key: "type",
    header: "ประเภท",
    render: ({ source }) => (
      <Badge variant="outline">{SOURCE_TYPE_LABELS[source.type].th}</Badge>
    ),
  },
  {
    key: "policy",
    header: "นโยบาย ToS",
    render: ({ source }) => (
      <span title={source.tos_policy}>
        <Badge variant="green">✅ อนุญาต</Badge>
      </span>
    ),
  },
  {
    key: "last_status",
    header: "ผลการตรวจล่าสุด",
    render: ({ source }) =>
      source.last_status ? (
        <div>
          <Badge variant={sourceStatusBadge(source.last_status)}>
            {sourceStatusLabel(source.last_status)}
          </Badge>
          <p className="mt-1 whitespace-nowrap text-xs text-slate-400">
            {formatDateTimeTH(source.last_checked_at)}
          </p>
        </div>
      ) : (
        <Badge variant="outline">ยังไม่เคยตรวจ</Badge>
      ),
  },
  {
    key: "enabled",
    header: "เปิดใช้งาน",
    render: ({ source }) => (
      // Read-only visual switch — management lives on the competitors page.
      <span
        role="img"
        aria-label={source.enabled ? "เปิดใช้งาน" : "ปิดใช้งาน"}
        className={`inline-flex h-5 w-9 items-center rounded-full px-0.5 transition-colors ${
          source.enabled ? "justify-end bg-blue-600" : "justify-start bg-slate-200"
        }`}
      >
        <span className="h-4 w-4 rounded-full bg-white shadow" />
      </span>
    ),
  },
];

function SourcesTable({ sources }: { sources: SourceRow[] | null }) {
  if (!sources) {
    return (
      <p className="py-6 text-center text-sm text-slate-400">
        API ยังไม่เชื่อมต่อ — แสดงทะเบียนแหล่งข้อมูลไม่ได้
      </p>
    );
  }
  return (
    <DataTable
      columns={SOURCE_COLUMNS}
      rows={sources}
      rowKey={({ source }) => source.id}
      emptyText="ยังไม่มีแหล่งข้อมูลในระบบ — เพิ่มได้ที่หน้าคู่แข่ง"
    />
  );
}

function ScheduleList({ jobs }: { jobs: Job[] | null }) {
  if (!jobs) {
    return (
      <p className="py-3 text-center text-sm text-slate-400">
        API ยังไม่เชื่อมต่อ — แสดงตารางงานอัตโนมัติไม่ได้
      </p>
    );
  }
  if (jobs.length === 0) {
    return <p className="py-3 text-center text-sm text-slate-400">ยังไม่มีงานอัตโนมัติในระบบ</p>;
  }
  return (
    <ul className="divide-y divide-slate-100">
      {jobs.map((job) => (
        <li key={job.id} className="flex items-center gap-3 px-5 py-3">
          <span
            className={`h-2 w-2 shrink-0 rounded-full ${
              !job.enabled
                ? "bg-slate-300"
                : job.last_status === "failed"
                  ? "bg-rose-500"
                  : "bg-emerald-500"
            }`}
          />
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium text-slate-800">{job.name}</p>
            <p className="text-xs text-slate-400">
              ทำงานล่าสุด {formatDateTimeTH(job.last_run_at)}
            </p>
          </div>
          <code className="rounded-md bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
            {job.cron}
          </code>
          {job.enabled ? (
            <Badge variant="green">เปิด</Badge>
          ) : (
            <Badge variant="neutral">ปิด</Badge>
          )}
        </li>
      ))}
    </ul>
  );
}

export default async function SettingsPage() {
  const [jobs, competitors] = await Promise.all([safe(listJobs()), safe(listCompetitors())]);

  const sources: SourceRow[] | null = competitors
    ? competitors.flatMap((competitor) =>
        competitor.sources.map((source) => ({
          competitorName: competitor.name,
          source,
        })),
      )
    : null;

  return (
    <div>
      <PageHeader title="ตั้งค่า" subtitle="แหล่งข้อมูล ตารางงานอัตโนมัติ และนโยบาย · Settings" />

      <div className="space-y-4">
        <Card>
          <CardHeader
            title="ทะเบียนแหล่งข้อมูล"
            subtitle="Sources registry — นโยบาย ToS บังคับใช้ในโค้ด (compliance.py) ไม่ใช่แค่ข้อตกลง"
            action={
              <div className="flex items-center gap-2">
                <Badge variant="blue" className="gap-1">
                  <ShieldCheck size={13} /> PDPA
                </Badge>
                <Link
                  href="/competitors"
                  className="whitespace-nowrap text-xs font-medium text-blue-600 hover:underline"
                >
                  จัดการที่หน้าคู่แข่ง
                </Link>
              </div>
            }
          />
          <CardContent>
            <SourcesTable sources={sources} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader
            title="ตารางงานอัตโนมัติ"
            subtitle="Schedules (อ่านอย่างเดียว) — จัดการผ่าน Celery Beat"
            action={
              <Badge variant="outline" className="gap-1">
                <CalendarClock size={13} /> เวลาไทย
              </Badge>
            }
          />
          <ScheduleList jobs={jobs} />
        </Card>
      </div>
    </div>
  );
}
