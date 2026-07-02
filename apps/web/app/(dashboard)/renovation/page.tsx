import type { Metadata } from "next";
import { AlertTriangle, CheckCircle2, CircleDashed, Clock } from "lucide-react";
import { BarList } from "@/components/BarList";
import { DataTable } from "@/components/DataTable";
import type { Column } from "@/components/DataTable";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { DrawCreateForm } from "@/components/renovation/DrawCreateForm";
import type { QuotationOption } from "@/components/renovation/DrawCreateForm";
import { MilestoneAdvanceButton } from "@/components/renovation/MilestoneAdvanceButton";
import { MilestoneCreateForm } from "@/components/renovation/MilestoneCreateForm";
import { PayDrawButton } from "@/components/renovation/PayDrawButton";
import { QuotationCreateForm } from "@/components/renovation/QuotationCreateForm";
import { Badge } from "@/components/ui/Badge";
import type { BadgeVariant } from "@/components/ui/Badge";
import { Card, CardContent, CardHeader } from "@/components/ui/Card";
import { Progress } from "@/components/ui/Progress";
import {
  getSiteSummary,
  listDraws,
  listSiteMilestones,
  listSiteQuotations,
  listSites,
  safe,
} from "@/lib/api";
import { formatDateTH, formatTHB, percentOf } from "@/lib/format";
import {
  categoryLabel,
  DRAW_ROW_STATUS_LABELS,
  MILESTONE_STATUS_LABELS,
  quotationStatusLabel,
} from "@/lib/i18n";
import type {
  DrawRow,
  DrawRowStatus,
  Milestone,
  MilestoneStatus,
  Quotation,
} from "@/lib/types";

export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "งานรีโนเวท" };

// ---------------------------------------------------------------------------
// Quotations
// ---------------------------------------------------------------------------

function quotationBadge(status: string): BadgeVariant {
  switch (status.toLowerCase()) {
    case "approved":
      return "green";
    case "rejected":
      return "red";
    case "pending":
      return "amber";
    default:
      return "neutral";
  }
}

function quotationColumns(contractorNames: Map<string, string>): Column<Quotation>[] {
  return [
    {
      key: "category",
      header: "หมวดงาน",
      render: (quotation) => (
        <span className="font-medium text-slate-900">{categoryLabel(quotation.category)}</span>
      ),
    },
    {
      key: "contractor",
      header: "ผู้รับเหมา",
      // Quotation rows carry only contractor_id — resolve the name via the
      // enriched draw rows; quotations without draws yet show "—".
      render: (quotation) => contractorNames.get(quotation.id) ?? "—",
    },
    {
      key: "amount",
      header: "จำนวนเงิน",
      align: "right",
      render: (quotation) => (
        <span className="font-medium text-slate-900">{formatTHB(quotation.amount_thb)}</span>
      ),
    },
    {
      key: "status",
      header: "สถานะ",
      render: (quotation) => (
        <Badge variant={quotationBadge(quotation.status)}>
          {quotationStatusLabel(quotation.status)}
        </Badge>
      ),
    },
  ];
}

// ---------------------------------------------------------------------------
// Draw pipeline
// ---------------------------------------------------------------------------

const DRAW_ROW_BADGE: Record<DrawRowStatus, BadgeVariant> = {
  pending: "amber",
  paid: "green",
  cancelled: "neutral",
};

const DRAW_COLUMNS: Column<DrawRow>[] = [
  {
    key: "seq",
    header: "งวดที่",
    render: (draw) => <span className="font-medium text-slate-900">#{draw.seq}</span>,
  },
  {
    key: "category",
    header: "งวด/หมวดงาน",
    render: (draw) => categoryLabel(draw.category),
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
      <Badge variant={DRAW_ROW_BADGE[draw.status]}>{DRAW_ROW_STATUS_LABELS[draw.status].th}</Badge>
    ),
  },
  {
    key: "dates",
    header: "วันที่ขอเบิก/จ่าย",
    render: (draw) => (
      <div className="text-xs">
        <p className="text-slate-700">ขอเบิก {formatDateTH(draw.requested_at)}</p>
        <p className="text-slate-400">
          {draw.paid_at ? `จ่ายแล้ว ${formatDateTH(draw.paid_at)}` : "ยังไม่จ่าย"}
        </p>
      </div>
    ),
  },
  {
    key: "actions",
    header: "จัดการ",
    render: (draw) =>
      draw.status === "pending" ? (
        <PayDrawButton
          drawId={draw.id}
          confirmText={`ยืนยันการจ่าย ${formatTHB(draw.amount_thb)} ให้ ${draw.contractor_name}?`}
        />
      ) : (
        <span className="text-xs text-slate-300">—</span>
      ),
  },
];

// ---------------------------------------------------------------------------
// Milestones
// ---------------------------------------------------------------------------

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

/** Past its planned date and not finished → highlight in red. */
function isOverdue(milestone: Milestone, now: Date): boolean {
  if (milestone.status === "done") return false;
  const planned = new Date(`${milestone.planned_date}T23:59:59`);
  return !Number.isNaN(planned.getTime()) && planned.getTime() < now.getTime();
}

function MilestoneList({ milestones, now }: { milestones: Milestone[]; now: Date }) {
  if (milestones.length === 0) {
    return <p className="py-2 text-sm text-slate-400">ยังไม่มีไมล์สโตน</p>;
  }
  return (
    <ul className="space-y-3">
      {milestones.map((milestone) => {
        const overdue = isOverdue(milestone, now);
        return (
          <li key={milestone.id} className="flex items-center gap-3">
            <MilestoneIcon status={milestone.status} />
            <div className="min-w-0 flex-1">
              <p
                className={`truncate text-sm font-medium ${overdue ? "text-rose-700" : "text-slate-800"}`}
              >
                {milestone.name}
              </p>
              <p className={`text-xs ${overdue ? "text-rose-500" : "text-slate-400"}`}>
                แผน {formatDateTH(milestone.planned_date)}
                {milestone.actual_date ? ` · จริง ${formatDateTH(milestone.actual_date)}` : ""}
              </p>
            </div>
            {overdue && <Badge variant="red">เลยกำหนด</Badge>}
            <Badge variant={MILESTONE_BADGE[milestone.status]}>
              {MILESTONE_STATUS_LABELS[milestone.status].th}
            </Badge>
            <MilestoneAdvanceButton milestoneId={milestone.id} status={milestone.status} />
          </li>
        );
      })}
    </ul>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default async function RenovationPage() {
  const sites = await safe(listSites());

  if (!sites) {
    return (
      <div>
        <PageHeader title="งานรีโนเวท" subtitle="งบประมาณ ใบเสนอราคา งวดเบิก และไมล์สโตนต่อไซต์ · Renovation" />
        <EmptyState />
      </div>
    );
  }

  const siteData = await Promise.all(
    sites.map(async (site) => {
      const [summary, quotations, draws, milestones] = await Promise.all([
        safe(getSiteSummary(site.id)),
        safe(listSiteQuotations(site.id)),
        safe(listDraws({ site_id: site.id })),
        safe(listSiteMilestones(site.id)),
      ]);
      return { summary, quotations, draws, milestones };
    }),
  );

  const now = new Date();

  return (
    <div>
      <PageHeader title="งานรีโนเวท" subtitle="งบประมาณ ใบเสนอราคา งวดเบิก และไมล์สโตนต่อไซต์ · Renovation" />

      <div className="space-y-6">
        {sites.map((site, index) => {
          const { summary, quotations, draws, milestones } = siteData[index];
          const spent = summary?.spent_thb ?? site.spend_summary?.spent_thb ?? 0;
          const outstanding =
            summary?.outstanding_draws_thb ?? site.spend_summary?.outstanding_thb ?? 0;
          const spentPct = percentOf(spent, site.budget_thb);

          // quotation_id → contractor_name from the enriched draw rows.
          const contractorNames = new Map(
            (draws ?? []).map((draw) => [draw.quotation_id, draw.contractor_name]),
          );

          const quotationOptions: QuotationOption[] = (quotations ?? []).map((quotation) => ({
            id: quotation.id,
            label: `${categoryLabel(quotation.category)} · ${formatTHB(quotation.amount_thb)}`,
          }));

          const siteMilestones = milestones ?? summary?.milestones ?? null;

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

                {/* Spend vs quotation by category */}
                {summary && (
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
                )}

                {/* Quotations */}
                <div className="space-y-3">
                  <h3 className="text-sm font-semibold text-slate-900">
                    ใบเสนอราคา <span className="font-normal text-slate-400">· Quotations</span>
                  </h3>
                  {quotations === null ? (
                    <p className="text-sm text-slate-400">
                      โหลดใบเสนอราคาไม่สำเร็จ — ลองรีเฟรชอีกครั้ง
                    </p>
                  ) : (
                    <DataTable
                      columns={quotationColumns(contractorNames)}
                      rows={quotations}
                      rowKey={(quotation) => quotation.id}
                      emptyText="ยังไม่มีใบเสนอราคา"
                    />
                  )}
                  <QuotationCreateForm siteId={site.id} />
                </div>

                {/* Draw pipeline */}
                <div className="space-y-3">
                  <h3 className="text-sm font-semibold text-slate-900">
                    งวดเบิก <span className="font-normal text-slate-400">· Draw pipeline</span>
                  </h3>
                  {draws === null ? (
                    <p className="text-sm text-slate-400">
                      โหลดงวดเบิกไม่สำเร็จ — ลองรีเฟรชอีกครั้ง
                    </p>
                  ) : (
                    <DataTable
                      columns={DRAW_COLUMNS}
                      rows={draws}
                      rowKey={(draw) => draw.id}
                      emptyText="ยังไม่มีงวดเบิก"
                    />
                  )}
                  <DrawCreateForm quotations={quotationOptions} />
                </div>

                {/* Milestones */}
                <div className="space-y-3">
                  <h3 className="text-sm font-semibold text-slate-900">
                    ไมล์สโตน <span className="font-normal text-slate-400">· Milestones</span>
                  </h3>
                  {siteMilestones === null ? (
                    <p className="text-sm text-slate-400">
                      โหลดไมล์สโตนไม่สำเร็จ — ลองรีเฟรชอีกครั้ง
                    </p>
                  ) : (
                    <MilestoneList milestones={siteMilestones} now={now} />
                  )}
                  <MilestoneCreateForm siteId={site.id} />
                </div>
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
