import { formatNumber } from "@/lib/format";

export interface DonutSegment {
  label: string;
  value: number;
  /** Tailwind text-* class — drawn via stroke/bg `currentColor`. */
  colorClass: string;
}

/**
 * Dependency-free SVG donut (circumference-100 dasharray trick).
 */
export function Donut({
  segments,
  centerValue,
  centerLabel,
}: {
  segments: DonutSegment[];
  centerValue: string;
  centerLabel: string;
}) {
  const total = segments.reduce((sum, seg) => sum + seg.value, 0);
  let cumulative = 0;

  return (
    <div className="flex flex-wrap items-center gap-6">
      <div className="relative h-36 w-36 shrink-0">
        <svg viewBox="0 0 36 36" className="h-full w-full" role="img" aria-label={centerLabel}>
          <circle
            cx="18"
            cy="18"
            r="15.9155"
            fill="none"
            strokeWidth="3.8"
            stroke="currentColor"
            className="text-slate-100"
          />
          {total > 0 &&
            segments
              .filter((seg) => seg.value > 0)
              .map((seg) => {
                const pct = (seg.value / total) * 100;
                const offset = 25 - cumulative;
                cumulative += pct;
                return (
                  <circle
                    key={seg.label}
                    cx="18"
                    cy="18"
                    r="15.9155"
                    fill="none"
                    strokeWidth="3.8"
                    stroke="currentColor"
                    strokeLinecap="butt"
                    className={seg.colorClass}
                    strokeDasharray={`${pct} ${100 - pct}`}
                    strokeDashoffset={offset}
                  />
                );
              })}
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-xl font-semibold text-slate-900">{centerValue}</span>
          <span className="text-xs text-slate-400">{centerLabel}</span>
        </div>
      </div>

      <ul className="min-w-[10rem] flex-1 space-y-2">
        {segments.map((seg) => (
          <li key={seg.label} className="flex items-center gap-2 text-sm">
            <span className={`h-2.5 w-2.5 shrink-0 rounded-full bg-current ${seg.colorClass}`} />
            <span className="flex-1 text-slate-600">{seg.label}</span>
            <span className="font-medium text-slate-900">{formatNumber(seg.value)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
