import type { Metadata } from "next";
import { AlertTriangle, CheckCircle2, CircleDashed, Clock } from "lucide-react";
import { BarList } from "@/components/BarList";
import { DataTable } from "@/components/DataTable";
import type { Column } from "@/components/DataTable";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/Badge";
import type { BadgeVariant } from "@/components/ui/Badge";
import { Card, CardContent, CardHeader } from "@/components/ui/Card";
import { Progress } from "@/components/ui/Progress";
import { getSiteSummary, listSites, safe } from "@/lib/api";
import { formatDateTH, formatTHB, percentOf } from "@/lib/format";
import { categoryLabel, DRAW_STATUS_LABELS, MILESTONE_STATUS_LABELS } from "@/lib/i18n";
import type { Draw, DrawStatus, Milestone, MilestoneStatus } from "@/lib/types";

export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "งานรีโนเวท" };

const DRAW_BADGE: Record<DrawStatus, BadgeVariant> = {
  requested: "amber",
  approved: "blue",
  paid: "green",
  rejected: "red",
};

const DRAW_COLUMNS: Column<Draw>[] = [
  {
    key: "seq",
    header: "งวดที่",
    render: (draw) => <span className="font-medium text-slate-900">#{draw.seq}</span>,
  },
  {
    key: "contractor",
    header: "ผู้รับเหมา",
    render: (draw) => draw.contractor_name,
  },
  {
    key: "amount",
    header: "จำนวนเงิน",
    align: "right",
    render: (draw) => <span className="font-medium text-slate-900">{formatTHB(draw.amount_thb)}</span>,
  },
  {
    key: "status",
    header: "สถานะ",
    render: (draw) => (
      <Badge variant={DRAW_BADGE[draw.status]}>{DRAW_STATUS_LABELS[draw.status].th}</Badge>
    ),
  },
  {
    key: "date",
    header: "วันที่",
    render: (draw) => formatDateTH(draw.paid_at ?? draw.requested_at),
  },
];

function MilestoneIcon({ status }: { status: MilestoneStatus }) {
  switch (status) {
    case "done":
      return <CheckCircle2 size={18} className="text-emerald-500" />;
    case "in_progress":
      return <Clock size={18} className="text-blue-500" />;
    case "delayed":
      return <AlertTriangle size={18} className="text-amber-500" />;
    case "planned":
      return <CircleDashed size={18} className="text-slate-300" />;
  }
}

const MILESTONE_BADGE: Record<MilestoneStatus, BadgeVariant> = {
  planned: "neutral",
  in_progress: "blue",
  done: "green",
  delayed: "amber",
};

function MilestoneList({ milestones }: { milestones: Milestone[] }) {
  if (milestones.length === 0) {
    return <p className="py-2 text-sm text-slate-400">ยังไม่มีไมล์สโตน</p>;
  }
  return (
    <ul className="space-y-3">
      {milestones.map((milestone) => (
        <li key={milestone.id} className="flex items-center gap-3">
          <MilestoneIcon status={milestone.status} />
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium text-slate-800">{milestone.name}</p>
            <p className="text-xs text-slate-400">
              แผน {formatDateTH(milestone.planned_date)}
              {milestone.actual_date ? ` · จริง ${formatDateTH(milestone.actual_date)}` : ""}
            </p>
          </div>
          <Badge variant={MILESTONE_BADGE[milestone.status]}>
            {MILESTONE_STATUS_LABELS[milestone.status].th}
          </Badge>
        </li>
      ))}
    </ul>
  );
}

export default async function RenovationPage() {
  const sites = await safe(listSites());

  if (!sites) {
    return (
      <div>
        <PageHeader title="งานรีโนเวท" subtitle="งบประมาณ งวดเบิก และไมล์สโตนต่อไซต์ · Renovation" />
        <EmptyState />
      </div>
    );
  }

  const summaries = await Promise.all(sites.map((site) => safe(getSiteSummary(site.id))));

  return (
    <div>
      <PageHeader title="งานรีโนเวท" subtitle="งบประมาณ งวดเบิก และไมล์สโตนต่อไซต์ · Renovation" />

      <div className="space-y-6">
        {sites.map((site, index) => {
          const summary = summaries[index];
          const spent = summary?.spent_thb ?? site.spend_summary?.spent_thb ?? 0;
          const outstanding =
            summary?.outstanding_draws_thb ?? site.spend_summary?.outstanding_thb ?? 0;
          const spentPct = percentOf(spent, site.budget_thb);

          return (
            <Card key={site.id}>
              <CardHeader
                title={site.name}
                subtitle={site.location}
                action={<Badge variant="blue">งบประมาณ {formatTHB(site.budget_thb)}</Badge>}
              />
              <CardContent className="space-y-6">
                {/* Budget vs spent */}
                <div>
                  <div className="flex items-baseline justify-between text-sm">
                    <span className="font-medium text-slate-800">
                      ใช้ไปแล้ว {formatTHB(spent)}
                    </span>
                    <span className="text-slate-400">{spentPct}% ของงบ</span>
                  </div>
                  <Progress
                    value={spent}
                    max={site.budget_thb}
                    className="mt-2"
                    barClassName={spentPct >= 90 ? "bg-amber-500" : "bg-blue-500"}
                  />
                  <p className="mt-1.5 text-xs text-slate-400">
                    คงเหลือ {formatTHB(Math.max(site.budget_thb - spent, 0))} · ค้างจ่าย{" "}
                    {formatTHB(outstanding)}
                  </p>
                </div>

                {summary ? (
                  <>
                    {/* Spend vs quotation by category */}
                    <div>
                      <h3 className="mb-3 text-sm font-semibold text-slate-900">
                        ค่าใช้จ่ายตามหมวด{" "}
                        <span className="font-normal text-slate-400">เทียบใบเสนอราคา</span>
                      </h3>
                      <BarList
                        items={summary.spend_by_category.map((cat) => ({
                          label: categoryLabel(cat.category),
                          value: cat.spent_thb,
                          display: `${formatTHB(cat.spent_thb)} / ${formatTHB(cat.quoted_thb)}`,
                        }))}
                        emptyText="ยังไม่มีรายการใช้จ่าย"
                      />
                    </div>

                    {/* Draw pipeline */}
                    <div>
                      <h3 className="mb-3 text-sm font-semibold text-slate-900">
                        งวดเบิก <span className="font-normal text-slate-400">· Draw pipeline</span>
                      </h3>
                      <DataTable
                        columns={DRAW_COLUMNS}
                        rows={summary.draws}
                        rowKey={(draw) => draw.id}
                        emptyText="ยังไม่มีงวดเบิก"
                      />
                    </div>

                    {/* Milestones */}
                    <div>
                      <h3 className="mb-3 text-sm font-semibold text-slate-900">
                        ไมล์สโตน <span className="font-normal text-slate-400">· Milestones</span>
                      </h3>
                      <MilestoneList milestones={summary.milestones} />
                    </div>
                  </>
                ) : (
                  <p className="text-sm text-slate-400">
                    โหลดข้อมูลสรุปของไซต์นี้ไม่สำเร็จ — ลองรีเฟรชอีกครั้ง
                  </p>
                )}
              </CardContent>
            </Card>
          );
        })}

        {sites.length === 0 && (
          <EmptyState
            title="ยังไม่มีไซต์ในระบบ"
            description="เพิ่มไซต์ Lipa Noi และ Chaweng ผ่าน API เพื่อเริ่มติดตามงบประมาณและงวดเบิก"
          />
        )}
      </div>
    </div>
  );
}
