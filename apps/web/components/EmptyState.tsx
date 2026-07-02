import { PlugZap } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { t } from "@/lib/i18n";

export function EmptyState({
  icon: Icon = PlugZap,
  title = t("common.apiOffline.title"),
  description = t("common.apiOffline.description"),
}: {
  icon?: LucideIcon;
  title?: string;
  description?: string;
}) {
  return (
    <div className="flex flex-col items-center rounded-2xl border border-dashed border-slate-300 bg-white px-6 py-16 text-center">
      <div className="rounded-2xl bg-slate-100 p-4 text-slate-400">
        <Icon size={28} />
      </div>
      <h2 className="mt-4 text-base font-semibold text-slate-900">{title}</h2>
      <p className="mt-1 max-w-md text-sm text-slate-500">{description}</p>
    </div>
  );
}
