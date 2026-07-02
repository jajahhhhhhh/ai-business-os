import type { Metadata } from "next";
import { DataTable } from "@/components/DataTable";
import type { Column } from "@/components/DataTable";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/Badge";
import type { BadgeVariant } from "@/components/ui/Badge";
import { Card, CardContent, CardHeader } from "@/components/ui/Card";
import { Progress } from "@/components/ui/Progress";
import { listAgentRuns, safe } from "@/lib/api";
import { formatDateTimeTH, formatDurationTH, formatNumber, formatUSD } from "@/lib/format";
import { RUN_STATUS_LABELS } from "@/lib/i18n";
import type { AgentRun, AgentRunStatus } from "@/lib/types";

export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "เอเจนต์" };

const RUN_BADGE: Record<AgentRunStatus, BadgeVariant> = {
  queued: "neutral",
  running: "blue",
  succeeded: "green",
  failed: "red",
};

/**
 * Placeholder daily budgets (USD) per agent — mirrors NFR-4 hard spend caps.
 * Will be replaced by a real endpoint once services/orchestrator/budget.py
 * exposes budgets through the API.
 */
const DAILY_BUDGET_USD: Record<string, number> = {
  planner: 3,
  research: 5,
  memory: 1,
  qa: 2,
  competitor: 2,
  analytics: 4,
};

const DEFAULT_BUDGET_USD = 2;

const RUN_COLUMNS: Column<AgentRun>[] = [
  {
    key: "agent",
    header: "เอเจนต์",
    render: (run) => (
      <div className="min-w-0">
        <p className="font-medium text-slate-900">{run.agent}</p>
        {run.error && <p className="truncate text-xs text-rose-500">{run.error}</p>}
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
    render: (run) => <span className="text-xs text-slate-500">{run.model}</span>,
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

export default async function AgentsPage() {
  const runsPage = await safe(listAgentRuns());

  if (!runsPage) {
    return (
      <div>
        <PageHeader title="เอเจนต์" subtitle="ประวัติการทำงาน ค่าใช้จ่าย และงบรายวันต่อเอเจนต์ · Agents" />
        <EmptyState />
      </div>
    );
  }

  const runs = runsPage.items;

  // Today's spend per agent (server-local day).
  const todayStart = new Date();
  todayStart.setHours(0, 0, 0, 0);
  const costToday = new Map<string, number>();
  for (const run of runs) {
    const started = new Date(run.started_at);
    if (!Number.isNaN(started.getTime()) && started >= todayStart) {
      costToday.set(run.agent, (costToday.get(run.agent) ?? 0) + run.cost_usd);
    }
  }
  const agents = Array.from(new Set(runs.map((run) => run.agent))).sort();

  return (
    <div>
      <PageHeader title="เอเจนต์" subtitle="ประวัติการทำงาน ค่าใช้จ่าย และงบรายวันต่อเอเจนต์ · Agents" />

      <div className="grid gap-4 lg:grid-cols-3">
        {/* Daily budget bars */}
        <Card>
          <CardHeader title="งบประมาณรายวัน" subtitle="Daily LLM budget ต่อเอเจนต์ (USD)" />
          <CardContent>
            {agents.length === 0 ? (
              <p className="py-2 text-sm text-slate-400">ยังไม่มีเอเจนต์ทำงานวันนี้</p>
            ) : (
              <div className="space-y-4">
                {agents.map((agent) => {
                  const spent = costToday.get(agent) ?? 0;
                  const budget = DAILY_BUDGET_USD[agent] ?? DEFAULT_BUDGET_USD;
                  const ratio = budget > 0 ? spent / budget : 0;
                  return (
                    <div key={agent}>
                      <div className="mb-1 flex items-baseline justify-between text-sm">
                        <span className="font-medium text-slate-700">{agent}</span>
                        <span className="text-xs text-slate-400">
                          {formatUSD(spent)} / {formatUSD(budget)}
                        </span>
                      </div>
                      <Progress
                        value={spent}
                        max={budget}
                        barClassName={
                          ratio >= 1 ? "bg-rose-500" : ratio >= 0.8 ? "bg-amber-500" : "bg-blue-500"
                        }
                      />
                    </div>
                  );
                })}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Run history */}
        <div className="lg:col-span-2">
          <Card>
            <CardHeader
              title="ประวัติการทำงาน"
              subtitle="Run history"
              action={<Badge variant="blue">{formatNumber(runs.length)} รายการ</Badge>}
            />
            <CardContent>
              <DataTable
                columns={RUN_COLUMNS}
                rows={runs}
                rowKey={(run) => run.id}
                emptyText="ยังไม่มีประวัติการทำงานของเอเจนต์"
              />
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
