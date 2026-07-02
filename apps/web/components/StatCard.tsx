import { ArrowDownRight, ArrowUpRight } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Card } from "@/components/ui/Card";

export function StatCard({
  title,
  value,
  icon: Icon,
  delta,
  hint,
}: {
  title: string;
  value: string;
  icon: LucideIcon;
  /** Percentage change vs previous period — omit when there is no baseline. */
  delta?: number;
  hint?: string;
}) {
  const positive = (delta ?? 0) >= 0;
  return (
    <Card className="p-5">
      <div className="flex items-start justify-between">
        <div className="rounded-xl bg-blue-50 p-2.5 text-blue-600">
          <Icon size={20} />
        </div>
        {delta !== undefined && (
          <span
            className={`flex items-center gap-0.5 text-xs font-semibold ${
              positive ? "text-emerald-600" : "text-rose-600"
            }`}
          >
            {positive ? <ArrowUpRight size={14} /> : <ArrowDownRight size={14} />}
            {positive ? "+" : ""}
            {delta.toFixed(0)}%
          </span>
        )}
      </div>
      <p className="mt-4 text-sm text-slate-500">{title}</p>
      <p className="mt-1 text-2xl font-semibold tracking-tight text-slate-900">{value}</p>
      {hint && <p className="mt-1 text-xs text-slate-400">{hint}</p>}
    </Card>
  );
}
