import type { Metadata } from "next";
import Link from "next/link";
import { AlertTriangle, Banknote, Radar, UserPlus, Wallet } from "lucide-react";
import { BarList } from "@/components/BarList";
import { Donut } from "@/components/Donut";
import { EmptyState } from "@/components/EmptyState";
import { HeroSignalCard } from "@/components/HeroSignalCard";
import { PageHeader } from "@/components/PageHeader";
import { StatCard } from "@/components/StatCard";
import { Badge } from "@/components/ui/Badge";
import type { BadgeVariant } from "@/components/ui/Badge";
import { Card, CardContent, CardHeader } from "@/components/ui/Card";
import {
  getSiteSummary,
  listAgentRuns,
  listCompetitorChanges,
  listCompetitors,
  listLeads,
  listSites,
  safe,
} from "@/lib/api";
import { formatDateTimeTH, formatTHB, formatTHBCompact } from "@/lib/format";
import { categoryLabel, DRAW_STATUS_LABELS, RUN_STATUS_LABELS } from "@/lib/i18n";
import type { AgentRunStatus, DrawStatus, SiteSummary } from "@/lib/types";

export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "ภาพรวม" };

const RUN_DOT: Record<AgentRunStatus, string> = {
  queued: "bg-slate-300",
  running: "bg-blue-500",
  succeeded: "bg-emerald-500",
  failed: "bg-rose-500",
};

const RUN_BADGE: Record<AgentRunStatus, BadgeVariant> = {
  queued: "neutral",
  running: "blue",
  succeeded: "green",
  failed: "red",
};

function inMonth(iso: string, year: number, month: number): boolean {
  const date = new Date(iso);
  return date.getFullYear() === year && date.getMonth() === month;
}

export default async function OverviewPage() {
  const [sites, leadsPage, runsPage, competitors] = await Promise.all([
    safe(listSites()),
    safe(listLeads()),
    safe(listAgentRuns()),
    safe(listCompetitors()),
  ]);

  // API fully unreachable → graceful fallback, never a crash.
  if (!sites && !leadsPage && !runsPage && !competitors) {
    return (
      <div>
        <PageHeader title="ภาพรวม" subtitle="สัญญาณสำคัญของธุรกิจวันนี้ · Overview" />
        <EmptyState />
      </div>
    );
  }

  const summaries: SiteSummary[] = sites
    ? (await Promise.all(sites.map((site) => safe(getSiteSummary(site.id))))).filter(
        (summary): summary is SiteSummary => summary !== null,
      )
    : [];

  const changeCount = competitors
    ? (await Promise.all(competitors.map((c) => safe(listCompetitorChanges(c.id))))).reduce(
        (acc, list) => {
          if (!list) return acc;
          acc.total += list.length;
          acc.high += list.filter((ch) => ch.severity === "high" || ch.severity === "critical").length;
          return acc;
        },
        { total: 0, high: 0 },
      )
    : { total: 0, high: 0 };

  const allDraws = summaries.flatMap((summary) => summary.draws);
  const outstanding = summaries.reduce((sum, s) => sum + s.outstanding_draws_thb, 0);
  const outstandingCount = allDraws.filter(
    (draw) => draw.status === "requested" || draw.status === "approved",
  ).length;

  const now = new Date();
  const prevMonth = new Date(now.getFullYear(), now.getMonth() - 1, 1);
  const paidInMonth = (year: number, month: number) =>
    allDraws.reduce(
      (sum, draw) =>
        draw.status === "paid" && draw.paid_at && inMonth(draw.paid_at, year, month)
          ? sum + draw.amount_thb
          : sum,
      0,
    );
  const spentThisMonth = paidInMonth(now.getFullYear(), now.getMonth());
  const spentPrevMonth = paidInMonth(prevMonth.getFullYear(), prevMonth.getMonth());
  const monthDelta =
    spentPrevMonth > 0 ? ((spentThisMonth - spentPrevMonth) / spentPrevMonth) * 100 : undefined;

  const newLeads = leadsPage ? leadsPage.items.filter((lead) => lead.stage === "discovered").length : 0;
  const failedRuns = runsPage ? runsPage.items.filter((run) => run.status === "failed").length : 0;
  const recentRuns = runsPage ? runsPage.items.slice(0, 6) : [];

  const drawCountByStatus = (status: DrawStatus) =>
    allDraws.filter((draw) => draw.status === status).length;
  const donutSegments = [
    { label: DRAW_STATUS_LABELS.paid.th, value: drawCountByStatus("paid"), colorClass: "text-blue-600" },
    { label: DRAW_STATUS_LABELS.approved.th, value: drawCountByStatus("approved"), colorClass: "text-sky-400" },
    { label: DRAW_STATUS_LABELS.requested.th, value: drawCountByStatus("requested"), colorClass: "text-amber-400" },
    { label: DRAW_STATUS_LABELS.rejected.th, value: drawCountByStatus("rejected"), colorClass: "text-slate-300" },
  ];

  return (
    <div>
      <PageHeader title="ภาพรวม" subtitle="สัญญาณสำคัญของธุรกิจวันนี้ · Overview" />

      <HeroSignalCard
        title="สัญญาณวันนี้ · Today's signal"
        headline={formatTHB(outstanding)}
        description={`ยอดงวดเบิกค้างจ่ายรวม ${outstandingCount} งวด จาก ${summaries.length} ไซต์ — ตรวจสอบและอนุมัติการจ่ายให้ MR.HOME เพื่อให้งานเดินต่อไม่สะดุด`}
        ctaHref="/renovation"
        ctaLabel="ไปที่งานรีโนเวท"
      />

      <div className="mt-6 grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-5">
        <StatCard
          title="ยอดเบิกค้างจ่าย"
          value={formatTHBCompact(outstanding)}
          icon={Banknote}
          hint={`${outstandingCount} งวดรอจ่าย`}
        />
        <StatCard
          title="ใช้ไปเดือนนี้"
          value={formatTHBCompact(spentThisMonth)}
          icon={Wallet}
          delta={monthDelta}
          hint="เทียบกับเดือนก่อน"
        />
        <StatCard
          title="ลูกค้า/ลีดใหม่"
          value={String(newLeads)}
          icon={UserPlus}
          hint="สถานะค้นพบใหม่"
        />
        <StatCard
          title="ความเคลื่อนไหวคู่แข่ง"
          value={String(changeCount.total)}
          icon={Radar}
          hint={`${changeCount.high} รายการระดับสูงขึ้นไป`}
        />
        <StatCard
          title="เอเจนต์ล้มเหลว"
          value={String(failedRuns)}
          icon={AlertTriangle}
          hint="จากประวัติการทำงานล่าสุด"
        />
      </div>

      <div className="mt-6 grid gap-4 lg:grid-cols-3">
        {/* Spend by category per site */}
        <div className="space-y-4 lg:col-span-2">
          {summaries.map((summary) => (
            <Card key={summary.site.id}>
              <CardHeader
                title={`ค่าใช้จ่ายตามหมวด — ${summary.site.name}`}
                subtitle={summary.site.location}
                action={<Badge variant="blue">รวม {formatTHB(summary.spent_thb)}</Badge>}
              />
              <CardContent>
                <BarList
                  items={summary.spend_by_category.map((cat) => ({
                    label: categoryLabel(cat.category),
                    value: cat.spent_thb,
                    display: formatTHB(cat.spent_thb),
                  }))}
                  emptyText="ยังไม่มีรายการใช้จ่าย"
                />
              </CardContent>
            </Card>
          ))}
          {summaries.length === 0 && (
            <Card>
              <CardContent>
                <p className="py-4 text-center text-sm text-slate-400">
                  ยังไม่มีข้อมูลไซต์จาก /v1/renovation/sites
                </p>
              </CardContent>
            </Card>
          )}
        </div>

        {/* Draw status donut + agent status list */}
        <div className="space-y-4">
          <Card>
            <CardHeader title="สถานะงวดเบิก" subtitle="Draw status" />
            <CardContent>
              <Donut
                segments={donutSegments}
                centerValue={String(allDraws.length)}
                centerLabel="งวดทั้งหมด"
              />
            </CardContent>
          </Card>

          <Card>
            <CardHeader
              title="สถานะเอเจนต์"
              subtitle="Agent activity"
              action={
                <Link href="/agents" className="text-xs font-medium text-blue-600 hover:underline">
                  ดูทั้งหมด
                </Link>
              }
            />
            {recentRuns.length === 0 ? (
              <CardContent>
                <p className="py-2 text-center text-sm text-slate-400">ยังไม่มีการทำงานของเอเจนต์</p>
              </CardContent>
            ) : (
              <ul className="divide-y divide-slate-100">
                {recentRuns.map((run) => (
                  <li key={run.id} className="flex items-center gap-3 px-5 py-3">
                    <span className={`h-2 w-2 shrink-0 rounded-full ${RUN_DOT[run.status]}`} />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium text-slate-800">{run.agent}</p>
                      <p className="truncate text-xs text-slate-400">
                        {run.model} · {formatDateTimeTH(run.started_at)}
                      </p>
                    </div>
                    <Badge variant={RUN_BADGE[run.status]}>{RUN_STATUS_LABELS[run.status].th}</Badge>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}
