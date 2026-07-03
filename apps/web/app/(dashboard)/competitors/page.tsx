import type { Metadata } from "next";
import { ExternalLink, Radar } from "lucide-react";
import { CheckButton } from "@/components/competitors/CheckButton";
import { CompetitorActiveToggle } from "@/components/competitors/CompetitorActiveToggle";
import { CompetitorCreateForm } from "@/components/competitors/CompetitorCreateForm";
import { SeverityFilterChips } from "@/components/competitors/SeverityFilterChips";
import { SourceCreateForm } from "@/components/competitors/SourceCreateForm";
import { SourceDeleteButton } from "@/components/competitors/SourceDeleteButton";
import { WeeklyReportButton } from "@/components/competitors/WeeklyReportButton";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/Badge";
import type { BadgeVariant } from "@/components/ui/Badge";
import { Card, CardContent, CardHeader } from "@/components/ui/Card";
import { listCompetitorChanges, listCompetitors, safe } from "@/lib/api";
import { formatDateTimeTH, formatNumber } from "@/lib/format";
import {
  changeCategoryLabel,
  competitorKindLabel,
  SEVERITY_LABELS,
  SOURCE_TYPE_LABELS,
  sourceStatusLabel,
} from "@/lib/i18n";
import type { ChangeSeverity, Competitor, CompetitorSource } from "@/lib/types";

export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "คู่แข่ง" };

const FEED_LIMIT = 50;

const SEVERITY_BADGE: Record<ChangeSeverity, BadgeVariant> = {
  critical: "red",
  high: "orange",
  medium: "amber",
  low: "neutral",
};

const SEVERITIES: ChangeSeverity[] = ["low", "medium", "high", "critical"];

/** Validate the ?severity= search param against the API vocabulary. */
function parseSeverity(value: string | string[] | undefined): ChangeSeverity | null {
  const raw = Array.isArray(value) ? value[0] : value;
  return SEVERITIES.find((severity) => severity === raw) ?? null;
}

/** Hostname without www. — keeps source chips scannable; falls back to the raw URL. */
function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

/** Chip tone from the collector's last_status (free string, never crashes). */
type SourceTone = "neutral" | "blue" | "red";

function sourceTone(status: string | null): SourceTone {
  if (!status) return "neutral";
  const slug = status.toLowerCase();
  if (slug === "changed") return "blue";
  if (slug === "error" || slug === "blocked" || slug === "refused") return "red";
  // baseline / unchanged / ok / unknown values stay neutral.
  return "neutral";
}

const SOURCE_CHIP_CLASS: Record<SourceTone, string> = {
  neutral: "border-slate-200 bg-slate-50 text-slate-600",
  blue: "border-blue-200 bg-blue-50 text-blue-700",
  red: "border-rose-200 bg-rose-50 text-rose-700",
};

function SourceChip({
  competitorId,
  source,
}: {
  competitorId: string;
  source: CompetitorSource;
}) {
  const host = hostOf(source.url);
  const statusText = sourceStatusLabel(source.last_status);
  const checkedText = source.last_checked_at
    ? `ตรวจล่าสุด ${formatDateTimeTH(source.last_checked_at)}`
    : "ยังไม่เคยตรวจ";
  return (
    <li
      title={`${source.url}\nสถานะ: ${statusText}\n${checkedText}`}
      className={`inline-flex max-w-full items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs ${
        SOURCE_CHIP_CLASS[sourceTone(source.last_status)]
      } ${source.enabled ? "" : "opacity-50"}`.trim()}
    >
      <span className="shrink-0 font-medium">{SOURCE_TYPE_LABELS[source.type].th}</span>
      <span className="truncate">{host}</span>
      {source.last_checked_at && (
        <span className="shrink-0 whitespace-nowrap opacity-70">
          · {formatDateTimeTH(source.last_checked_at)}
        </span>
      )}
      <SourceDeleteButton competitorId={competitorId} sourceId={source.id} label={host} />
    </li>
  );
}

function CompetitorCard({ competitor }: { competitor: Competitor }) {
  return (
    <Card className={competitor.active ? "" : "opacity-60"}>
      <CardContent className="space-y-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="truncate text-sm font-semibold text-slate-900">
                {competitor.name}
              </h3>
              <Badge variant="outline">{competitorKindLabel(competitor.kind)}</Badge>
              {!competitor.active && <Badge variant="neutral">ปิดติดตาม</Badge>}
            </div>
            {competitor.website ? (
              <a
                href={competitor.website}
                target="_blank"
                rel="noopener noreferrer"
                title={competitor.website}
                className="mt-1 inline-flex max-w-full items-center gap-1 text-xs text-slate-400 transition-colors hover:text-blue-600"
              >
                <span className="truncate">{hostOf(competitor.website)}</span>
                <ExternalLink size={12} className="shrink-0" />
              </a>
            ) : (
              <p className="mt-1 text-xs text-slate-300">ไม่มีเว็บไซต์</p>
            )}
          </div>
          <CompetitorActiveToggle
            competitorId={competitor.id}
            active={competitor.active}
            name={competitor.name}
          />
        </div>

        {competitor.sources.length > 0 ? (
          <ul className="flex flex-wrap gap-1.5">
            {competitor.sources.map((source) => (
              <SourceChip key={source.id} competitorId={competitor.id} source={source} />
            ))}
          </ul>
        ) : (
          <p className="text-xs text-slate-400">
            ยังไม่มีแหล่งข้อมูล — เพิ่มเว็บไซต์หรือฟีด RSS เพื่อเริ่มตรวจ
          </p>
        )}

        <SourceCreateForm competitorId={competitor.id} />

        <div className="border-t border-slate-100 pt-3">
          <CheckButton competitorId={competitor.id} />
        </div>
      </CardContent>
    </Card>
  );
}

export default async function CompetitorsPage({
  searchParams,
}: {
  searchParams: Promise<{ severity?: string | string[] }>;
}) {
  const severity = parseSeverity((await searchParams).severity);

  const [competitors, changes] = await Promise.all([
    safe(listCompetitors()),
    safe(
      listCompetitorChanges({
        severity: severity ?? undefined,
        limit: FEED_LIMIT,
      }),
    ),
  ]);

  const header = (
    <PageHeader
      title="คู่แข่ง"
      subtitle="ติดตามวิลล่าคู่แข่งบนเกาะสมุย · Competitors"
      action={<WeeklyReportButton />}
    />
  );

  // API fully unreachable → graceful fallback, never a crash.
  if (!competitors && !changes) {
    return (
      <div>
        {header}
        <EmptyState />
      </div>
    );
  }

  const activeCount = (competitors ?? []).filter((competitor) => competitor.active).length;

  return (
    <div>
      {header}

      <div className="space-y-6">
        {/* Add competitor */}
        <Card>
          <CardHeader
            title="เพิ่มคู่แข่ง"
            subtitle="ใส่ชื่อ เว็บไซต์ และฟีด RSS — ระบบตรวจนโยบายแหล่งข้อมูลให้อัตโนมัติ"
          />
          <CardContent>
            <CompetitorCreateForm />
          </CardContent>
        </Card>

        {/* Competitor cards */}
        <section aria-label="คู่แข่งที่ติดตาม" className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-semibold text-slate-900">คู่แข่งที่ติดตาม</h2>
            {competitors && (
              <Badge variant="blue">
                ติดตามอยู่ {formatNumber(activeCount)}/{formatNumber(competitors.length)} ราย
              </Badge>
            )}
          </div>
          {!competitors ? (
            <Card>
              <CardContent>
                <p className="py-4 text-center text-sm text-slate-400">
                  API ยังไม่เชื่อมต่อ — แสดงทะเบียนคู่แข่งไม่ได้
                </p>
              </CardContent>
            </Card>
          ) : competitors.length === 0 ? (
            <Card>
              <CardContent>
                <p className="py-4 text-center text-sm text-slate-400">
                  ยังไม่มีคู่แข่งในระบบ — เพิ่มวิลล่าคู่แข่งรายแรกด้านบนเพื่อเริ่มติดตาม
                </p>
              </CardContent>
            </Card>
          ) : (
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {competitors.map((competitor) => (
                <CompetitorCard key={competitor.id} competitor={competitor} />
              ))}
            </div>
          )}
        </section>

        {/* Change feed */}
        <Card>
          <CardHeader
            title="ฟีดความเคลื่อนไหว"
            subtitle="Change feed — เรียงจากรายการล่าสุด"
            action={
              changes !== null ? (
                <Badge variant="blue">{formatNumber(changes.length)} รายการ</Badge>
              ) : undefined
            }
          />
          <CardContent className="border-b border-slate-100 py-3">
            <SeverityFilterChips selected={severity} />
          </CardContent>

          {changes === null ? (
            <CardContent>
              <p className="py-6 text-center text-sm text-slate-400">
                API ยังไม่เชื่อมต่อ — แสดงฟีดความเคลื่อนไหวไม่ได้ ลองรีเฟรชหน้านี้อีกครั้ง
              </p>
            </CardContent>
          ) : changes.length === 0 ? (
            <CardContent>
              <div className="flex flex-col items-center py-8 text-center">
                <Radar size={22} className="text-slate-300" />
                <p className="mt-2 text-sm text-slate-400">
                  {severity
                    ? `ยังไม่มีความเคลื่อนไหวระดับ "${SEVERITY_LABELS[severity].th}" — ลองเลือก ทั้งหมด`
                    : "ยังไม่มีความเคลื่อนไหว — เพิ่มคู่แข่งและกด ตรวจตอนนี้"}
                </p>
              </div>
            </CardContent>
          ) : (
            <ul className="divide-y divide-slate-100">
              {changes.map((change) => (
                <li key={change.id} className="px-5 py-4">
                  <div className="flex items-start justify-between gap-3">
                    <p className="min-w-0 text-sm leading-relaxed text-slate-800">
                      <span className="font-semibold text-slate-900">
                        {change.competitor_name}
                      </span>{" "}
                      — {change.summary}
                    </p>
                    <Badge variant={SEVERITY_BADGE[change.severity]}>
                      {SEVERITY_LABELS[change.severity].th}
                    </Badge>
                  </div>
                  <p className="mt-1.5 flex flex-wrap items-center gap-1.5 text-xs text-slate-400">
                    <Badge variant="outline">{changeCategoryLabel(change.category)}</Badge>
                    <span>{formatDateTimeTH(change.detected_at)}</span>
                  </p>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}
