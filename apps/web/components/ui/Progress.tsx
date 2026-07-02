export function Progress({
  value,
  max = 100,
  className = "",
  barClassName = "bg-blue-500",
}: {
  value: number;
  max?: number;
  className?: string;
  barClassName?: string;
}) {
  const pct = max > 0 ? Math.min(Math.max((value / max) * 100, 0), 100) : 0;
  return (
    <div className={`h-2 w-full overflow-hidden rounded-full bg-slate-100 ${className}`.trim()}>
      <div className={`h-full rounded-full ${barClassName}`} style={{ width: `${pct}%` }} />
    </div>
  );
}
