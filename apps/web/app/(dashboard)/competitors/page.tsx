import type { Metadata } from "next";
import { Globe } from "lucide-react";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/Badge";
import type { BadgeVariant } from "@/components/ui/Badge";
import { Card, CardContent, CardHeader } from "@/components/ui/Card";
import { listCompetitorChanges, listCompetitors, safe } from "@/lib/api";
import { formatDateTimeTH, formatNumber } from "@/lib/format";
import { SEVERITY_LABELS } from "@/lib/i18n";
import type { ChangeSeverity, CompetitorChange } from "@/lib/types";

export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "คู่แข่ง" };

const SEVERITY_BADGE: Record<ChangeSeverity, BadgeVariant> = {
  low: "neutral",
  medium: "blue",
  high: "amber",
  critical: "red",
};

interface FeedEntry {
  change: CompetitorChange;
  competitorName: string;
}

export default async function CompetitorsPage() {
  const competitors = await safe(listCompetitors());

  if (!competitors) {
    return (
      <div>
        <PageHeader title="คู่แข่ง" subtitle="ความเคลื่อนไหวของวิลล่าคู่แข่งบนเกาะสมุย · Competitors" />
        <EmptyState />
      </div>
    );
  }

  const changeLists = await Promise.all(
    competitors.map((competitor) => safe(listCompetitorChanges(competitor.id))),
  );

  const feed: FeedEntry[] = [];
  changeLists.forEach((list, index) => {
    if (!list) return;
    const competitorName = competitors[index].name;
    for (const change of list) {
      feed.push({ change, competitorName });
    }
  });
  feed.sort((a, b) => b.change.detected_at.localeCompare(a.change.detected_at));

  return (
    <div>
      <PageHeader title="คู่แข่ง" subtitle="ความเคลื่อนไหวของวิลล่าคู่แข่งบนเกาะสมุย · Competitors" />

      <div className="grid gap-4 lg:grid-cols-3">
        {/* Change feed */}
        <div className="lg:col-span-2">
          <Card>
            <CardHeader
              title="ฟีดความเคลื่อนไหว"
              subtitle="Change feed — อัปเดตทุกวัน 06:00 น."
              action={<Badge variant="blue">{formatNumber(feed.length)} รายการ</Badge>}
            />
            {feed.length === 0 ? (
              <CardContent>
                <p className="py-6 text-center text-sm text-slate-400">
                  ยังไม่พบความเคลื่อนไหว — ระบบเก็บข้อมูลจะสะสม snapshot ของคู่แข่งทุกวัน
                </p>
              </CardContent>
            ) : (
              <ul className="divide-y divide-slate-100">
                {feed.map(({ change, competitorName }) => (
                  <li key={change.id} className="px-5 py-4">
                    <div className="flex items-start justify-between gap-3">
                      <p className="text-sm leading-relaxed text-slate-800">{change.summary}</p>
                      <Badge variant={SEVERITY_BADGE[change.severity]}>
                        {SEVERITY_LABELS[change.severity].th}
                      </Badge>
                    </div>
                    <p className="mt-1.5 text-xs text-slate-400">
                      {competitorName} · {change.category} · {formatDateTimeTH(change.detected_at)}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>

        {/* Competitor set */}
        <div>
          <Card>
            <CardHeader
              title="คู่แข่งที่ติดตาม"
              subtitle={`${formatNumber(competitors.length)} ราย (คัดเลือกโดยเจ้าของ)`}
            />
            {competitors.length === 0 ? (
              <CardContent>
                <p className="py-4 text-center text-sm text-slate-400">
                  ยังไม่มีคู่แข่งในระบบ — เพิ่มวิลล่าคู่แข่งย่าน Lipa Noi และ Chaweng ได้ที่ตั้งค่า
                </p>
              </CardContent>
            ) : (
              <ul className="divide-y divide-slate-100">
                {competitors.map((competitor) => (
                  <li key={competitor.id} className="flex items-center gap-3 px-5 py-3">
                    <span
                      className={`h-2 w-2 shrink-0 rounded-full ${
                        competitor.active ? "bg-emerald-500" : "bg-slate-300"
                      }`}
                    />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium text-slate-800">{competitor.name}</p>
                      <p className="truncate text-xs text-slate-400">{competitor.kind}</p>
                    </div>
                    <a
                      href={competitor.website}
                      target="_blank"
                      rel="noopener noreferrer"
                      title={competitor.website}
                      className="text-slate-300 transition-colors hover:text-blue-600"
                    >
                      <Globe size={16} />
                    </a>
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
