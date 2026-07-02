import type { Metadata } from "next";
import { DataTable } from "@/components/DataTable";
import type { Column } from "@/components/DataTable";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/Badge";
import type { BadgeVariant } from "@/components/ui/Badge";
import { Card, CardContent, CardHeader } from "@/components/ui/Card";
import { listLeads, safe } from "@/lib/api";
import { formatDateTH, formatNumber } from "@/lib/format";
import { LEAD_KIND_LABELS, LEAD_STAGE_LABELS } from "@/lib/i18n";
import type { Lead, LeadStage } from "@/lib/types";

export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "ลูกค้า" };

const STAGES: LeadStage[] = ["discovered", "qualified", "contacted", "won", "lost"];

const STAGE_CHIP: Record<LeadStage, string> = {
  discovered: "border-blue-100 bg-blue-50 text-blue-700",
  qualified: "border-sky-100 bg-sky-50 text-sky-700",
  contacted: "border-amber-100 bg-amber-50 text-amber-700",
  won: "border-emerald-100 bg-emerald-50 text-emerald-700",
  lost: "border-slate-200 bg-slate-50 text-slate-500",
};

const STAGE_BADGE: Record<LeadStage, BadgeVariant> = {
  discovered: "blue",
  qualified: "blue",
  contacted: "amber",
  won: "green",
  lost: "neutral",
};

function scoreVariant(score: number): BadgeVariant {
  if (score >= 70) return "green";
  if (score >= 40) return "amber";
  return "neutral";
}

const LEAD_COLUMNS: Column<Lead>[] = [
  {
    key: "name",
    header: "ชื่อ",
    render: (lead) => (
      <div className="min-w-0">
        <p className="truncate font-medium text-slate-900">{lead.name}</p>
        {lead.source && <p className="truncate text-xs text-slate-400">{lead.source}</p>}
      </div>
    ),
  },
  {
    key: "kind",
    header: "ประเภท",
    render: (lead) => <Badge variant="outline">{LEAD_KIND_LABELS[lead.kind].th}</Badge>,
  },
  {
    key: "score",
    header: "คะแนนความสนใจ",
    align: "right",
    render: (lead) => (
      <Badge variant={scoreVariant(lead.intent_score)}>{formatNumber(lead.intent_score)}</Badge>
    ),
  },
  {
    key: "stage",
    header: "สถานะ",
    render: (lead) => (
      <Badge variant={STAGE_BADGE[lead.stage]}>{LEAD_STAGE_LABELS[lead.stage].th}</Badge>
    ),
  },
  {
    key: "activity",
    header: "กิจกรรมล่าสุด",
    render: (lead) => formatDateTH(lead.last_activity_at ?? lead.first_seen_at),
  },
];

export default async function LeadsPage() {
  const leadsPage = await safe(listLeads());

  if (!leadsPage) {
    return (
      <div>
        <PageHeader title="ลูกค้า" subtitle="ไปป์ไลน์ลีดที่ระบบค้นพบและติดตาม · Leads" />
        <EmptyState />
      </div>
    );
  }

  const leads = leadsPage.items;
  const countByStage = (stage: LeadStage) => leads.filter((lead) => lead.stage === stage).length;

  return (
    <div>
      <PageHeader title="ลูกค้า" subtitle="ไปป์ไลน์ลีดที่ระบบค้นพบและติดตาม · Leads" />

      {/* Pipeline stage summary chips */}
      <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {STAGES.map((stage) => (
          <div key={stage} className={`rounded-2xl border px-4 py-3 ${STAGE_CHIP[stage]}`}>
            <p className="text-2xl font-bold tracking-tight">{formatNumber(countByStage(stage))}</p>
            <p className="mt-0.5 text-xs font-medium">
              {LEAD_STAGE_LABELS[stage].th}
              <span className="font-normal opacity-60"> · {LEAD_STAGE_LABELS[stage].en}</span>
            </p>
          </div>
        ))}
      </div>

      <Card>
        <CardHeader
          title="รายชื่อลีดทั้งหมด"
          subtitle={`${formatNumber(leads.length)} รายการ${leadsPage.next_cursor ? " (มีหน้าถัดไป)" : ""}`}
        />
        <CardContent>
          <DataTable
            columns={LEAD_COLUMNS}
            rows={leads}
            rowKey={(lead) => lead.id}
            emptyText="ยังไม่มีลีดในระบบ — ระบบค้นหาลีดจะเริ่มทำงานในเฟส C"
          />
        </CardContent>
      </Card>
    </div>
  );
}
