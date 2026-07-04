import type { Metadata } from "next";
import Link from "next/link";
import {
  ArrowLeft,
  Contact,
  ExternalLink,
  MessageSquareQuote,
  ShieldCheck,
  UserX,
} from "lucide-react";
import { EmptyState } from "@/components/EmptyState";
import { CopySuggestionButton } from "@/components/leads/CopySuggestionButton";
import { LeadAdvanceButtons } from "@/components/leads/LeadAdvanceButtons";
import { Badge } from "@/components/ui/Badge";
import type { BadgeVariant } from "@/components/ui/Badge";
import { Card, CardContent, CardHeader } from "@/components/ui/Card";
import { getLead, safe } from "@/lib/api";
import { formatDateTimeTH, formatNumber, formatRelativeTH } from "@/lib/format";
import {
  LEAD_KIND_LABELS,
  LEAD_STAGE_LABELS,
  leadEventLabel,
  leadFeatureLabel,
} from "@/lib/i18n";
import type { LeadEvent, LeadStage } from "@/lib/types";

export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "รายละเอียดลีด" };

const STAGE_BADGE: Record<LeadStage, BadgeVariant> = {
  discovered: "blue",
  qualified: "blue",
  contacted: "amber",
  won: "green",
  lost: "neutral",
};

/** Score badge: ≥70 น่าติดต่อ (green) · 40–69 พอไปได้ (amber) · ต่ำกว่า slate. */
function scoreVariant(score: number): BadgeVariant {
  if (score >= 70) return "green";
  if (score >= 40) return "amber";
  return "neutral";
}

/** Readable Thai rendering of a score-feature value (unknown shape → JSON). */
function featureValue(value: unknown): string {
  if (typeof value === "boolean") return value ? "ใช่" : "ไม่ใช่";
  if (typeof value === "number") return formatNumber(value);
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value) ?? "—";
  } catch {
    return "—";
  }
}

const STAGE_SLUGS: LeadStage[] = ["discovered", "qualified", "contacted", "won", "lost"];

/** Thai stage label for a free-string payload value; falls back to the raw value. */
function stageLabelOf(value: unknown): string | null {
  if (typeof value !== "string" || value === "") return null;
  const match = STAGE_SLUGS.find((stage) => stage === value.toLowerCase());
  return match ? LEAD_STAGE_LABELS[match].th : value;
}

/** Post excerpt carried in discovered/reobserved/classified event payloads. */
function excerptOf(event: LeadEvent): string | null {
  const excerpt = event.payload["excerpt"];
  return typeof excerpt === "string" && excerpt.trim() !== "" ? excerpt : null;
}

/** "เปลี่ยนสถานะ: ค้นพบใหม่ → คัดกรองแล้ว" when the payload carries from/to. */
function stageChangeText(event: LeadEvent): string | null {
  if (event.type.toLowerCase() !== "stage_changed") return null;
  const from = stageLabelOf(event.payload["from"]);
  const to = stageLabelOf(event.payload["to"]);
  if (!from || !to) return null;
  return `${from} → ${to}`;
}

export default async function LeadDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const lead = await safe(getLead(id));

  // Unknown lead id (404) and unreachable API degrade the same way — the
  // board is the recovery path either way.
  if (!lead) {
    return (
      <div>
        <Link
          href="/leads"
          className="mb-4 inline-flex items-center gap-1.5 text-sm text-slate-500 transition-colors hover:text-blue-600"
        >
          <ArrowLeft size={14} />
          กลับไปหน้าลูกค้า
        </Link>
        <EmptyState
          icon={UserX}
          title="ไม่พบลีดนี้"
          description="ลีดอาจถูกลบตามนโยบาย PDPA แล้ว หรือ API ยังไม่เชื่อมต่อ — กลับไปหน้าลูกค้าแล้วลองอีกครั้ง"
        />
      </div>
    );
  }

  // Timeline newest-first, matching every other feed in the dashboard.
  const events = [...lead.events].sort((a, b) =>
    b.occurred_at.localeCompare(a.occurred_at),
  );
  const features = lead.score ? Object.entries(lead.score.features) : [];

  return (
    <div>
      <Link
        href="/leads"
        className="mb-4 inline-flex items-center gap-1.5 text-sm text-slate-500 transition-colors hover:text-blue-600"
      >
        <ArrowLeft size={14} />
        กลับไปหน้าลูกค้า
      </Link>

      {/* Header — identity, score, stage + advance actions */}
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="truncate text-2xl font-bold tracking-tight text-slate-900">
            {lead.name}
          </h1>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <Badge variant="outline">{LEAD_KIND_LABELS[lead.kind].th}</Badge>
            <Badge variant={scoreVariant(lead.intent_score)}>
              คะแนน {formatNumber(lead.intent_score)}
            </Badge>
            <Badge variant={STAGE_BADGE[lead.stage]}>
              {LEAD_STAGE_LABELS[lead.stage].th}
            </Badge>
            {lead.source && <span className="text-xs text-slate-400">{lead.source}</span>}
            <span className="text-xs text-slate-400">
              กิจกรรมล่าสุด {formatRelativeTH(lead.last_activity_at ?? lead.first_seen_at)}
            </span>
          </div>
        </div>
        <LeadAdvanceButtons leadId={lead.id} stage={lead.stage} />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-1">
          {/* Contact — PDPA-minimal, owner-only */}
          <Card>
            <CardHeader title="ข้อมูลติดต่อ" subtitle="เห็นเฉพาะเจ้าของ · Owner only" />
            <CardContent className="space-y-3">
              {lead.contact ? (
                <dl className="space-y-2 text-sm">
                  <div className="flex items-center justify-between gap-3">
                    <dt className="text-xs text-slate-400">แพลตฟอร์ม</dt>
                    <dd className="font-medium text-slate-900">{lead.contact.platform}</dd>
                  </div>
                  <div className="flex items-center justify-between gap-3">
                    <dt className="text-xs text-slate-400">ชื่อผู้ใช้</dt>
                    <dd className="truncate font-medium text-slate-900">
                      {lead.contact.handle}
                    </dd>
                  </div>
                  <div className="flex items-center justify-between gap-3">
                    <dt className="text-xs text-slate-400">ลิงก์</dt>
                    <dd className="min-w-0">
                      <a
                        href={lead.contact.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        title={lead.contact.url}
                        className="inline-flex max-w-full items-center gap-1 text-sm text-blue-600 transition-colors hover:text-blue-700"
                      >
                        <span className="truncate">เปิดโพสต์ต้นทาง</span>
                        <ExternalLink size={12} className="shrink-0" />
                      </a>
                    </dd>
                  </div>
                </dl>
              ) : (
                <div className="flex flex-col items-center py-4 text-center">
                  <Contact size={20} className="text-slate-300" />
                  <p className="mt-2 text-sm text-slate-400">
                    ไม่มีข้อมูลติดต่อ — ยังไม่พบ หรือถูกลบตามนโยบายแล้ว
                  </p>
                </div>
              )}
              <p className="flex items-start gap-1.5 rounded-xl bg-slate-50 px-3 py-2 text-xs text-slate-500">
                <ShieldCheck size={13} className="mt-0.5 shrink-0 text-slate-400" />
                ข้อมูลสาธารณะเท่านั้น — ลบอัตโนมัติหลังไม่มีการเคลื่อนไหว 18 เดือน
              </p>
            </CardContent>
          </Card>

          {/* Score features */}
          <Card>
            <CardHeader
              title="ปัจจัยคะแนนความสนใจ"
              subtitle={
                lead.score
                  ? `คะแนน ${formatNumber(lead.score.value)} · โมเดล ${lead.score.model_version}`
                  : "ยังไม่มีการให้คะแนน"
              }
            />
            <CardContent>
              {lead.score && features.length > 0 ? (
                <ul className="flex flex-wrap gap-1.5">
                  {features.map(([key, value]) => (
                    <li key={key}>
                      <Badge variant="outline">
                        {leadFeatureLabel(key)}
                        <span className="font-normal text-slate-400">
                          {featureValue(value)}
                        </span>
                      </Badge>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="py-2 text-center text-sm text-slate-400">
                  ยังไม่มีปัจจัยคะแนน — รอเอเจนต์วิเคราะห์รอบถัดไป
                </p>
              )}
            </CardContent>
          </Card>
        </div>

        <div className="space-y-4 lg:col-span-2">
          {/* Follow-up suggestion */}
          <Card>
            <CardHeader
              title="คำแนะนำการติดตาม"
              subtitle="ร่างข้อความจากเอเจนต์ — ตรวจก่อนส่งเสมอ"
            />
            <CardContent className="space-y-3">
              {lead.suggestion ? (
                <>
                  <p className="whitespace-pre-wrap rounded-xl bg-slate-50 px-4 py-3 text-sm leading-relaxed text-slate-800">
                    {lead.suggestion}
                  </p>
                  <CopySuggestionButton text={lead.suggestion} />
                </>
              ) : (
                <div className="flex flex-col items-center py-6 text-center">
                  <MessageSquareQuote size={20} className="text-slate-300" />
                  <p className="mt-2 text-sm text-slate-400">
                    ยังไม่มีคำแนะนำ — เอเจนต์จะวิเคราะห์และร่างข้อความให้หลังคัดกรองลีด
                  </p>
                </div>
              )}
            </CardContent>
          </Card>

          {/* Timeline */}
          <Card>
            <CardHeader
              title="ไทม์ไลน์"
              subtitle="ประวัติการพบและการเปลี่ยนสถานะ — เรียงจากล่าสุด"
              action={<Badge variant="blue">{formatNumber(events.length)} รายการ</Badge>}
            />
            {events.length === 0 ? (
              <CardContent>
                <p className="py-4 text-center text-sm text-slate-400">
                  ยังไม่มีเหตุการณ์ในไทม์ไลน์
                </p>
              </CardContent>
            ) : (
              <ul className="divide-y divide-slate-100">
                {events.map((event, index) => {
                  const excerpt = excerptOf(event);
                  const stageChange = stageChangeText(event);
                  return (
                    <li key={`${event.occurred_at}-${event.type}-${index}`} className="px-5 py-3.5">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <p className="text-sm font-medium text-slate-900">
                          {leadEventLabel(event.type)}
                          {stageChange && (
                            <span className="ml-2 font-normal text-slate-500">
                              {stageChange}
                            </span>
                          )}
                        </p>
                        <span className="text-xs text-slate-400">
                          {formatDateTimeTH(event.occurred_at)}
                        </span>
                      </div>
                      {excerpt && (
                        <blockquote className="mt-2 border-l-2 border-slate-200 pl-3 text-xs leading-relaxed text-slate-500">
                          {excerpt}
                        </blockquote>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}
