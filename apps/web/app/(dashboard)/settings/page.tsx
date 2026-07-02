import type { Metadata } from "next";
import { CalendarClock, ShieldCheck } from "lucide-react";
import { DataTable } from "@/components/DataTable";
import type { Column } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/Badge";
import { Card, CardContent, CardHeader } from "@/components/ui/Card";
import { listJobs, safe } from "@/lib/api";
import { formatDateTimeTH } from "@/lib/format";
import type { Job } from "@/lib/types";

export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "ตั้งค่า" };

/**
 * Sources registry concept — mirrors the ToS policy matrix in
 * docs/ARCHITECTURE.md §8.4. Read-only for now; will be served by
 * GET /v1/sources once the collector registry lands in the API.
 */
interface SourceConcept {
  name: string;
  type: string;
  policy: "allowed" | "restricted";
  policyNote: string;
  enabled: boolean;
}

const SOURCE_REGISTRY: SourceConcept[] = [
  {
    name: "Reddit (r/kohsamui, r/Thailand)",
    type: "API ทางการ",
    policy: "allowed",
    policyNote: "ใช้ OAuth API ตามเงื่อนไข + จำกัดอัตราเรียก",
    enabled: true,
  },
  {
    name: "RSS / บล็อกท่องเที่ยว",
    type: "ฟีด / HTTP",
    policy: "allowed",
    policyNote: "เคารพ robots.txt และแคช",
    enabled: true,
  },
  {
    name: "Google Places API",
    type: "API ทางการ (เสียเงิน)",
    policy: "allowed",
    policyNote: "ห้าม scrape SERP — ใช้ API เท่านั้น",
    enabled: true,
  },
  {
    name: "จดหมายข่าวคู่แข่ง (Gmail)",
    type: "อีเมล",
    policy: "allowed",
    policyNote: "สมัครรับอย่างถูกต้อง แล้ว parse จากกล่องจดหมาย",
    enabled: true,
  },
  {
    name: "Facebook Pages / Groups",
    type: "นำเข้าเอง",
    policy: "restricted",
    policyNote: "ToS ห้าม scrape — ใช้ Graph API ของเพจตัวเอง หรือเจ้าของส่งต่อเท่านั้น",
    enabled: false,
  },
  {
    name: "Airbnb / Booking / Agoda",
    type: "ข้อมูลผู้ให้บริการ",
    policy: "restricted",
    policyNote: "ห้าม scrape — ใช้ API ลิสติ้งตัวเอง หรือข้อมูลตลาดแบบมีสัญญา (AirDNA)",
    enabled: false,
  },
];

const SOURCE_COLUMNS: Column<SourceConcept>[] = [
  {
    key: "name",
    header: "แหล่งข้อมูล",
    render: (source) => (
      <div className="min-w-0">
        <p className="font-medium text-slate-900">{source.name}</p>
        <p className="mt-0.5 text-xs text-slate-400">{source.policyNote}</p>
      </div>
    ),
  },
  {
    key: "type",
    header: "ประเภท",
    render: (source) => <Badge variant="outline">{source.type}</Badge>,
  },
  {
    key: "policy",
    header: "นโยบาย ToS",
    render: (source) =>
      source.policy === "allowed" ? (
        <Badge variant="green">✅ อนุญาต</Badge>
      ) : (
        <Badge variant="amber">⚠️ จำกัด</Badge>
      ),
  },
  {
    key: "enabled",
    header: "เปิดใช้งาน",
    render: (source) => (
      // Read-only visual toggle — editing arrives with the sources API.
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
  const jobs = await safe(listJobs());

  return (
    <div>
      <PageHeader title="ตั้งค่า" subtitle="แหล่งข้อมูล ตารางงานอัตโนมัติ และนโยบาย · Settings" />

      <div className="space-y-4">
        <Card>
          <CardHeader
            title="ทะเบียนแหล่งข้อมูล"
            subtitle="Sources registry — นโยบาย ToS บังคับใช้ในโค้ด (compliance.py) ไม่ใช่แค่ข้อตกลง"
            action={
              <Badge variant="blue" className="gap-1">
                <ShieldCheck size={13} /> PDPA
              </Badge>
            }
          />
          <CardContent>
            <DataTable
              columns={SOURCE_COLUMNS}
              rows={SOURCE_REGISTRY}
              rowKey={(source) => source.name}
            />
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
