export interface BarListItem {
  label: string;
  value: number;
  /** Pre-formatted value shown on the right (e.g. "฿1,200,000"). */
  display?: string;
}

export function BarList({
  items,
  barClassName = "bg-blue-500",
  emptyText = "ไม่มีข้อมูล",
}: {
  items: BarListItem[];
  barClassName?: string;
  emptyText?: string;
}) {
  if (items.length === 0) {
    return <p className="py-2 text-sm text-slate-400">{emptyText}</p>;
  }
  const max = Math.max(...items.map((item) => item.value), 1);
  return (
    <div className="space-y-3">
      {items.map((item) => {
        const pct = item.value <= 0 ? 0 : Math.max((item.value / max) * 100, 2);
        return (
          <div key={item.label}>
            <div className="mb-1 flex items-baseline justify-between gap-3 text-sm">
              <span className="truncate text-slate-600">{item.label}</span>
              <span className="whitespace-nowrap font-medium text-slate-900">
                {item.display ?? String(item.value)}
              </span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-slate-100">
              <div className={`h-full rounded-full ${barClassName}`} style={{ width: `${pct}%` }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}
