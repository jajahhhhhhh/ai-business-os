import type { Metadata } from "next";
import { ClipboardCheck } from "lucide-react";
import { AgentTriggerCard } from "@/components/agents/AgentTriggerCard";
import { DataTable } from "@/components/DataTable";
import type { Column } from "@/components/DataTable";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/Badge";
import type { BadgeVariant } from "@/components/ui/Badge";
import { Card, CardContent, CardHeader } from "@/components/ui/Card";
import { Progress } from "@/components/ui/Progress";
import { listAgentCosts, listAgentEvals, listAgentRuns, safe } from "@/lib/api";
import {
  formatDateTH,
  formatDateTimeTH,
  formatDurationTH,
  formatNumber,
  formatUSD,
} from "@/lib/format";
import { agentLabel, RUN_STATUS_LABELS } from "@/lib/i18n";
import type { AgentCost, AgentRun, AgentRunStatus } from "@/lib/types";

export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "เอเจนต์" };

const COST_WINDOW_DAYS = 7;
const RUNS_LIMIT = 50;
const EVALS_LIMIT = 50;
/** Tallest daily bar of the 7-day cost chart, px. */
const CHART_HEIGHT_PX = 140;

const RUN_BADGE: Record<AgentRunStatus, BadgeVariant> = {
  queued: "neutral",
  running: "blue",
  succeeded: "green",
  failed: "red",
  parked: "amber",
  over_budget: "red",
};

/** Per-agent segment colors of the stacked chart — assigned by sorted order. */
const AGENT_COLORS = [
  "bg-blue-500",
  "bg-emerald-500",
  "bg-amber-500",
  "bg-violet-500",
  "bg-rose-500",
  "bg-sky-500",
  "bg-teal-500",
  "bg-orange-500",
] as const;

// ---------------------------------------------------------------------------
// Bangkok-day helpers — cost rows are keyed by Bangkok-local "YYYY-MM-DD"
// ---------------------------------------------------------------------------

/** en-CA yields "YYYY-MM-DD" — matches the API's Bangkok day key. */
const BANGKOK_DAY = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Bangkok" });

/** Dates arrive as plain "YYYY-MM-DD" (UTC midnight) — format in UTC to avoid shifting. */
const WEEKDAY_TH = new Intl.DateTimeFormat("th-TH", { weekday: "short", timeZone: "UTC" });

function bangkokToday(): string {
  return BANGKOK_DAY.format(new Date());
}

/** Last `count` Bangkok days ending today, oldest first. */
function lastBangkokDays(count: number): string[] {
  const [year, month, day] = bangkokToday().split("-").map(Number);
  const todayUtc = Date.UTC(year, month - 1, day);
  return Array.from({ length: count }, (_, i) =>
    new Date(todayUtc - (count - 1 - i) * 86_400_000).toISOString().slice(0, 10),
  );
}

/** Thai short weekday for a "YYYY-MM-DD" day, e.g. "ศ." */
function weekdayTH(day: string): string {
  const date = new Date(`${day}T00:00:00Z`);
  return Number.isNaN(date.getTime()) ? day : WEEKDAY_TH.format(date);
}

// ---------------------------------------------------------------------------
// Section helpers
// ---------------------------------------------------------------------------

/** NFR-4 budget tones: เขียว <60% · เหลือง <90% · แดง ≥90%. */
function budgetBarClass(spent: number, budget: number | null): string {
  if (budget === null || budget <= 0) return "bg-slate-300";
  const ratio = spent / budget;
  if (ratio >= 0.9) return "bg-rose-500";
  if (ratio >= 0.6) return "bg-amber-500";
  return "bg-emerald-500";
}

/** Eval score tones: ≥80 เขียว · 50–79 เหลือง · <50 แดง. */
function scoreVariant(score: number): BadgeVariant {
  if (score >= 80) return "green";
  if (score >= 50) return "amber";
  return "red";
}

interface TodayBudgetRow {
  agent: string;
  spent_usd: number;
  runs: number;
  budget_usd: number | null;
}

/** Aggregate today's cost rows per agent (defensive — normally one row each). */
function todayBudgetRows(costs: AgentCost[], today: string): TodayBudgetRow[] {
  const byAgent = new Map<string, TodayBudgetRow>();
  for (const row of costs) {
    if (row.day !== today) continue;
    const entry = byAgent.get(row.agent) ?? {
      agent: row.agent,
      spent_usd: 0,
      runs: 0,
      budget_usd: null,
    };
    entry.spent_usd += row.cost_usd;
    entry.runs += row.runs;
    if (row.budget_usd !== null) entry.budget_usd = row.budget_usd;
    byAgent.set(row.agent, entry);
  }
  return Array.from(byAgent.values()).sort((a, b) => a.agent.localeCompare(b.agent));
}

const RUN_COLUMNS: Column<AgentRun>[] = [
  {
    key: "agent",
    header: "เอเจนต์",
    render: (run) => (
      <div className="min-w-0">
        <p className="font-medium text-slate-900">{agentLabel(run.agent)}</p>
        {run.error && (
          <p title={run.error} className="max-w-56 truncate text-xs text-rose-500">
            {run.error}
          </p>
        )}
      </div>
    ),
  },
  {
    key: "status",
    header: "สถานะ",
    render: (run) => (
      <Badge variant={RUN_BADGE[run.status]}>{RUN_STATUS_LABELS[run.status].th}</Badge>
    ),
  },
  {
    key: "model",
    header: "โมเดล",
    render: (run) =>
      run.model.toLowerCase().includes("fallback") ? (
        <span title="ใช้โมเดลสำรอง">
          <Badge variant="amber">{run.model}</Badge>
        </span>
      ) : (
        <span className="text-xs text-slate-500">{run.model}</span>
      ),
  },
  {
    key: "tokens",
    header: "โทเคน (เข้า/ออก)",
    align: "right",
    render: (run) => (
      <span className="text-xs text-slate-500">
        {formatNumber(run.tokens_in)} / {formatNumber(run.tokens_out)}
      </span>
    ),
  },
  {
    key: "cost",
    header: "ค่าใช้จ่าย",
    align: "right",
    render: (run) => <span className="font-medium text-slate-900">{formatUSD(run.cost_usd)}</span>,
  },
  {
    key: "started",
    header: "เริ่มเมื่อ",
    render: (run) => formatDateTimeTH(run.started_at),
  },
  {
    key: "duration",
    header: "ระยะเวลา",
    render: (run) => (
      <span className="text-slate-500">{formatDurationTH(run.started_at, run.finished_at)}</span>
    ),
  },
];

const OFFLINE_NOTE = "API ยังไม่เชื่อมต่อ — แสดงข้อมูลส่วนนี้ไม่ได้ ลองรีเฟรชหน้านี้อีกครั้ง";

function OfflineNote() {
  return <p className="py-4 text-center text-sm text-slate-400">{OFFLINE_NOTE}</p>;
}

export default async function AgentsPage() {
  const [runsPage, costs, evals] = await Promise.all([
    safe(listAgentRuns({ limit: RUNS_LIMIT })),
    safe(listAgentCosts(COST_WINDOW_DAYS)),
    safe(listAgentEvals({ limit: EVALS_LIMIT })),
  ]);

  const header = (
    <PageHeader
      title="เอเจนต์"
      subtitle="งบประมาณ ค่าใช้จ่าย คุณภาพ และประวัติการทำงาน · Agents"
    />
  );

  // API fully unreachable → graceful fallback, never a crash.
  if (!runsPage && !costs && !evals) {
    return (
      <div>
        {header}
        <EmptyState />
      </div>
    );
  }

  const runs = runsPage ? runsPage.items : [];

  const today = bangkokToday();
  const budgetRows = costs ? todayBudgetRows(costs, today) : [];
  const maxSpentToday = Math.max(...budgetRows.map((row) => row.spent_usd), 0);

  // 7-day stacked chart: day → agent → cost, agents colored by sorted order.
  const days = lastBangkokDays(COST_WINDOW_DAYS);
  const costByDayAgent = new Map<string, Map<string, number>>();
  for (const row of costs ?? []) {
    const dayMap = costByDayAgent.get(row.day) ?? new Map<string, number>();
    dayMap.set(row.agent, (dayMap.get(row.agent) ?? 0) + row.cost_usd);
    costByDayAgent.set(row.day, dayMap);
  }
  const chartAgents = Array.from(new Set((costs ?? []).map((row) => row.agent))).sort();
  const colorOf = (agent: string) =>
    AGENT_COLORS[Math.max(chartAgents.indexOf(agent), 0) % AGENT_COLORS.length];
  const dayTotals = days.map((day) => {
    const dayMap = costByDayAgent.get(day);
    return dayMap ? Array.from(dayMap.values()).reduce((sum, cost) => sum + cost, 0) : 0;
  });
  const maxDayTotal = Math.max(...dayTotals, 0);
  const weekTotal = dayTotals.reduce((sum, total) => sum + total, 0);

  return (
    <div>
      {header}

      <div className="grid gap-4 lg:grid-cols-3">
        {/* 1 · Today's budget bars */}
        <Card>
          <CardHeader
            title="งบประมาณวันนี้"
            subtitle={`Daily LLM budget ต่อเอเจนต์ (USD) · ${formatDateTH(today)}`}
          />
          <CardContent>
            {!costs ? (
              <OfflineNote />
            ) : budgetRows.length === 0 ? (
              <p className="py-2 text-sm text-slate-400">ยังไม่มีการใช้จ่ายของเอเจนต์วันนี้</p>
            ) : (
              <div className="space-y-4">
                {budgetRows.map((row) => (
                  <div key={row.agent}>
                    <div className="mb-1 flex items-baseline justify-between gap-3 text-sm">
                      <span className="truncate font-medium text-slate-700">
                        {agentLabel(row.agent)}
                      </span>
                      <span className="whitespace-nowrap text-xs text-slate-400">
                        {row.budget_usd !== null
                          ? `${formatUSD(row.spent_usd)} / ${formatUSD(row.budget_usd)}`
                          : formatUSD(row.spent_usd)}
                      </span>
                    </div>
                    <Progress
                      value={row.spent_usd}
                      max={row.budget_usd ?? Math.max(maxSpentToday, 1)}
                      barClassName={budgetBarClass(row.spent_usd, row.budget_usd)}
                    />
                    <p className="mt-1 text-xs text-slate-400">
                      {formatNumber(row.runs)} รอบวันนี้
                      {row.budget_usd === null && " · ไม่ได้ตั้งงบ"}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* 2 · 7-day stacked cost chart */}
        <div className="lg:col-span-2">
          <Card>
            <CardHeader
              title="ค่าใช้จ่าย 7 วันล่าสุด"
              subtitle="แยกตามเอเจนต์ ต่อวัน (USD)"
              action={
                costs ? <Badge variant="blue">รวม {formatUSD(weekTotal)}</Badge> : undefined
              }
            />
            <CardContent>
              {!costs ? (
                <OfflineNote />
              ) : (
                <div>
                  <div className="flex items-end gap-2 sm:gap-3">
                    {days.map((day, index) => {
                      const dayMap = costByDayAgent.get(day);
                      const total = dayTotals[index];
                      const barPx =
                        maxDayTotal > 0 && total > 0
                          ? Math.max(Math.round((total / maxDayTotal) * CHART_HEIGHT_PX), 3)
                          : 0;
                      const breakdown = chartAgents
                        .map((agent) => {
                          const cost = dayMap?.get(agent) ?? 0;
                          return cost > 0 ? `${agentLabel(agent)}: ${formatUSD(cost)}` : null;
                        })
                        .filter((line): line is string => line !== null);
                      const tooltip = [
                        `${weekdayTH(day)} ${formatDateTH(day)}`,
                        `รวม ${formatUSD(total)}`,
                        ...breakdown,
                      ].join("\n");
                      return (
                        <div
                          key={day}
                          title={tooltip}
                          className="flex min-w-0 flex-1 flex-col items-center gap-1.5"
                        >
                          {barPx > 0 ? (
                            <div
                              className="flex w-full max-w-10 flex-col-reverse overflow-hidden rounded-md"
                              style={{ height: `${barPx}px` }}
                            >
                              {chartAgents.map((agent) => {
                                const cost = dayMap?.get(agent) ?? 0;
                                if (cost <= 0 || total <= 0) return null;
                                return (
                                  <div
                                    key={agent}
                                    className={colorOf(agent)}
                                    style={{ height: `${(cost / total) * 100}%` }}
                                  />
                                );
                              })}
                            </div>
                          ) : (
                            <div className="h-0.5 w-full max-w-10 rounded-full bg-slate-100" />
                          )}
                          <span
                            className={`text-[11px] ${
                              day === today ? "font-semibold text-slate-600" : "text-slate-400"
                            }`}
                          >
                            {weekdayTH(day)}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                  {chartAgents.length > 0 ? (
                    <div className="mt-4 flex flex-wrap gap-x-4 gap-y-1.5 border-t border-slate-100 pt-3">
                      {chartAgents.map((agent) => (
                        <span
                          key={agent}
                          className="inline-flex items-center gap-1.5 text-xs text-slate-500"
                        >
                          <span
                            aria-hidden
                            className={`h-2.5 w-2.5 shrink-0 rounded-sm ${colorOf(agent)}`}
                          />
                          {agentLabel(agent)}
                        </span>
                      ))}
                    </div>
                  ) : (
                    <p className="mt-3 text-center text-sm text-slate-400">
                      ยังไม่มีค่าใช้จ่ายในช่วง 7 วันล่าสุด
                    </p>
                  )}
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        {/* 3 · Manual triggers */}
        <Card>
          <CardHeader
            title="สั่งงานเอเจนต์"
            subtitle="รันงานทันทีโดยไม่รอรอบอัตโนมัติ"
          />
          <CardContent>
            <AgentTriggerCard />
          </CardContent>
        </Card>

        {/* 4 · Eval scores */}
        <div className="lg:col-span-2">
          <Card>
            <CardHeader
              title="ผลประเมินคุณภาพ"
              subtitle="Eval scores จาก QA agent — เรียงจากรายการล่าสุด"
              action={
                evals ? (
                  <Badge variant="blue">{formatNumber(evals.length)} รายการ</Badge>
                ) : undefined
              }
            />
            {!evals ? (
              <CardContent>
                <OfflineNote />
              </CardContent>
            ) : evals.length === 0 ? (
              <CardContent>
                <div className="flex flex-col items-center py-8 text-center">
                  <ClipboardCheck size={22} className="text-slate-300" />
                  <p className="mt-2 text-sm text-slate-400">
                    ยังไม่มีผลประเมิน — QA agent จะรันทุกวันอาทิตย์
                  </p>
                </div>
              </CardContent>
            ) : (
              <ul className="divide-y divide-slate-100">
                {evals.map((evaluation) => (
                  <li key={evaluation.id} className="px-5 py-3.5">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="flex flex-wrap items-center gap-2 text-sm">
                          <span className="font-medium text-slate-900">
                            {agentLabel(evaluation.agent)}
                          </span>
                          <Badge variant="outline">{evaluation.rubric}</Badge>
                        </p>
                        {evaluation.notes && (
                          <p
                            title={evaluation.notes}
                            className="mt-1 max-w-md truncate text-xs text-slate-500"
                          >
                            {evaluation.notes}
                          </p>
                        )}
                        <p className="mt-1 text-xs text-slate-400">
                          {formatDateTimeTH(evaluation.created_at)}
                        </p>
                      </div>
                      <Badge variant={scoreVariant(evaluation.score)}>
                        {formatNumber(evaluation.score)}/100
                      </Badge>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>

        {/* 5 · Run history */}
        <div className="lg:col-span-3">
          <Card>
            <CardHeader
              title="ประวัติการทำงาน"
              subtitle="Run history"
              action={
                runsPage ? (
                  <Badge variant="blue">{formatNumber(runs.length)} รายการ</Badge>
                ) : undefined
              }
            />
            <CardContent>
              {!runsPage ? (
                <OfflineNote />
              ) : (
                <DataTable
                  columns={RUN_COLUMNS}
                  rows={runs}
                  rowKey={(run) => run.id}
                  emptyText="ยังไม่มีประวัติการทำงานของเอเจนต์"
                />
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
