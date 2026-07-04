import type { Metadata } from "next";
import Link from "next/link";
import { ExternalLink, Rss, UserSearch } from "lucide-react";
import { EmptyState } from "@/components/EmptyState";
import { LeadAdvanceButtons } from "@/components/leads/LeadAdvanceButtons";
import { LeadFilters } from "@/components/leads/LeadFilters";
import type { MinScoreFilter } from "@/components/leads/LeadFilters";
import { LeadSourceCollectButton } from "@/components/leads/LeadSourceCollectButton";
import { LeadSourceCreateForm } from "@/components/leads/LeadSourceCreateForm";
import { LeadSourceDeleteButton } from "@/components/leads/LeadSourceDeleteButton";
import { LeadSourceToggle } from "@/components/leads/LeadSourceToggle";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/Badge";
import type { BadgeVariant } from "@/components/ui/Badge";
import { Card, CardContent, CardHeader } from "@/components/ui/Card";
import { listLeads, listSources, safe } from "@/lib/api";
import { formatDateTimeTH, formatNumber, formatRelativeTH } from "@/lib/format";
import {
  LEAD_KIND_LABELS,
  LEAD_SOURCE_TYPE_LABELS,
  LEAD_STAGE_LABELS,
  sourceStatusLabel,
} from "@/lib/i18n";
import type { Lead, LeadKind, LeadSource, LeadStage } from "@/lib/types";

export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "ลูกค้า" };

/** One board fetch covers the whole pipeline — plenty for an owner-scale CRM. */
const BOARD_LIMIT = 200;

const STAGES: LeadStage[] = ["discovered", "qualified", "contacted", "won", "lost"];

const KINDS: LeadKind[] = ["guest", "longstay", "b2b", "supplier"];

/** Column accent on the count header, per pipeline stage. */
const STAGE_HEADER_CLASS: Record<LeadStage, string> = {
  discovered: "border-blue-100 bg-blue-50 text-blue-700",
  qualified: "border-sky-100 bg-sky-50 text-sky-700",
  contacted: "border-amber-100 bg-amber-50 text-amber-700",
  won: "border-emerald-100 bg-emerald-50 text-emerald-700",
  lost: "border-slate-200 bg-slate-50 text-slate-500",
};

/** Score badge: ≥70 น่าติดต่อ (green) · 40–69 พอไปได้ (amber) · ต่ำกว่า slate. */
function scoreVariant(score: number): BadgeVariant {
  if (score >= 70) return "green";
  if (score >= 40) return "amber";
  return "neutral";
}

/** Validate the ?kind= search param against the API vocabulary. */
function parseKind(value: string | string[] | undefined): LeadKind | null {
  const raw = Array.isArray(value) ? value[0] : value;
  return KINDS.find((kind) => kind === raw) ?? null;
}

/** Validate the ?min_score= search param against the offered options. */
function parseMinScore(value: string | string[] | undefined): MinScoreFilter | null {
  const raw = Array.isArray(value) ? value[0] : value;
  if (raw === "50") return 50;
  if (raw === "70") return 70;
  return null;
}

function parseQuery(value: string | string[] | undefined): string {
  const raw = Array.isArray(value) ? value[0] : value;
  return raw?.trim() ?? "";
}

/** Hostname without www. — keeps source cards scannable; falls back to the raw URL. */
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
  if (slug === "ok" || slug === "changed") return "blue";
  if (slug === "error" || slug === "blocked" || slug === "refused") return "red";
  return "neutral";
}

const SOURCE_CHIP_CLASS: Record<SourceTone, string> = {
  neutral: "border-slate-200 bg-slate-50 text-slate-600",
  blue: "border-blue-200 bg-blue-50 text-blue-700",
  red: "border-rose-200 bg-rose-50 text-rose-700",
};

function LeadCard({ lead }: { lead: Lead }) {
  // Closed deals read as history — keep them compact so open work stands out.
  const compact = lead.stage === "won" || lead.stage === "lost";
  const activityText = formatRelativeTH(lead.last_activity_at ?? lead.first_seen_at);

  return (
    <li className="rounded-xl border border-slate-200 bg-white p-3 shadow-sm">
      <div className="flex items-start justify-between gap-2">
        <Link
          href={`/leads/${lead.id}`}
          className="min-w-0 transition-colors hover:text-blue-600"
          title="ดูรายละเอียดลีด"
        >
          <p className="truncate text-sm font-medium text-slate-900 hover:text-blue-600">
            {lead.name}
          </p>
        </Link>
        <Badge variant={scoreVariant(lead.intent_score)}>
          {formatNumber(lead.intent_score)}
        </Badge>
      </div>

      <div
        className={`flex flex-wrap items-center gap-1.5 text-xs text-slate-400 ${compact ? "mt-1" : "mt-1.5"}`}
      >
        <Badge variant="outline">{LEAD_KIND_LABELS[lead.kind].th}</Badge>
        <span>{activityText}</span>
      </div>

      {!compact && (
        <div className="mt-2 border-t border-slate-100 pt-2">
          <LeadAdvanceButtons leadId={lead.id} stage={lead.stage} />
        </div>
      )}
    </li>
  );
}

function StageColumn({ stage, leads }: { stage: LeadStage; leads: Lead[] }) {
  return (
    <section aria-label={LEAD_STAGE_LABELS[stage].th} className="w-64 shrink-0">
      <header
        className={`flex items-center justify-between rounded-xl border px-3 py-2 ${STAGE_HEADER_CLASS[stage]}`}
      >
        <p className="text-xs font-semibold">
          {LEAD_STAGE_LABELS[stage].th}
          <span className="font-normal opacity-60"> · {LEAD_STAGE_LABELS[stage].en}</span>
        </p>
        <p className="text-sm font-bold tabular-nums">{formatNumber(leads.length)}</p>
      </header>
      {leads.length === 0 ? (
        <p className="mt-2 rounded-xl border border-dashed border-slate-200 px-3 py-4 text-center text-xs text-slate-400">
          ไม่มีลีดในสถานะนี้
        </p>
      ) : (
        <ul className="mt-2 max-h-[65vh] space-y-2 overflow-y-auto pb-1 pr-0.5">
          {leads.map((lead) => (
            <LeadCard key={lead.id} lead={lead} />
          ))}
        </ul>
      )}
    </section>
  );
}

function SourceCard({ source }: { source: LeadSource }) {
  const target =
    source.type === "reddit"
      ? source.config?.subreddit
        ? `r/${source.config.subreddit}`
        : "ไม่ระบุ subreddit"
      : source.url
        ? hostOf(source.url)
        : "ไม่ระบุ URL ฟีด";
  const checkedText = source.last_checked_at
    ? `ตรวจล่าสุด ${formatDateTimeTH(source.last_checked_at)}`
    : "ยังไม่เคยตรวจ";

  return (
    <Card className={source.enabled ? "" : "opacity-60"}>
      <CardContent className="space-y-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="truncate text-sm font-semibold text-slate-900">{source.name}</h3>
              <Badge variant="outline">
                <Rss size={11} />
                {LEAD_SOURCE_TYPE_LABELS[source.type].th}
              </Badge>
              {!source.enabled && <Badge variant="neutral">ปิดใช้งาน</Badge>}
            </div>
            {source.url ? (
              <a
                href={source.url}
                target="_blank"
                rel="noopener noreferrer"
                title={source.url}
                className="mt-1 inline-flex max-w-full items-center gap-1 text-xs text-slate-400 transition-colors hover:text-blue-600"
              >
                <span className="truncate">{target}</span>
                <ExternalLink size={12} className="shrink-0" />
              </a>
            ) : (
              <p className="mt-1 truncate text-xs text-slate-400">{target}</p>
            )}
            {source.type === "reddit" && source.config?.query && (
              <p className="mt-0.5 truncate text-xs text-slate-400">
                คำค้นหา: {source.config.query}
              </p>
            )}
          </div>
          <LeadSourceToggle sourceId={source.id} enabled={source.enabled} name={source.name} />
        </div>

        <div className="flex flex-wrap items-center gap-1.5 text-xs text-slate-400">
          <span
            className={`inline-flex items-center rounded-full border px-2.5 py-0.5 font-medium ${
              SOURCE_CHIP_CLASS[sourceTone(source.last_status)]
            }`}
          >
            {sourceStatusLabel(source.last_status)}
          </span>
          <span>{checkedText}</span>
          <span>· {formatNumber(source.rate_limit_per_hr)} ครั้ง/ชม.</span>
        </div>

        <div className="flex items-center justify-between gap-2 border-t border-slate-100 pt-3">
          <LeadSourceCollectButton sourceId={source.id} />
          <LeadSourceDeleteButton sourceId={source.id} name={source.name} />
        </div>
      </CardContent>
    </Card>
  );
}

export default async function LeadsPage({
  searchParams,
}: {
  searchParams: Promise<{
    kind?: string | string[];
    min_score?: string | string[];
    q?: string | string[];
  }>;
}) {
  const params = await searchParams;
  const kind = parseKind(params.kind);
  const minScore = parseMinScore(params.min_score);
  const q = parseQuery(params.q);

  const [leadsPage, sources] = await Promise.all([
    safe(
      listLeads({
        kind: kind ?? undefined,
        min_score: minScore ?? undefined,
        q: q !== "" ? q : undefined,
        limit: BOARD_LIMIT,
      }),
    ),
    safe(listSources()),
  ]);

  const header = (
    <PageHeader
      title="ลูกค้า"
      subtitle="ไปป์ไลน์ลีดจาก Reddit และฟีด RSS · Lead discovery CRM"
    />
  );

  // API fully unreachable → graceful fallback, never a crash.
  if (!leadsPage && !sources) {
    return (
      <div>
        {header}
        <EmptyState />
      </div>
    );
  }

  const leads = leadsPage?.items ?? [];
  const byStage = (stage: LeadStage) => leads.filter((lead) => lead.stage === stage);
  const hasFilter = kind !== null || minScore !== null || q !== "";
  const enabledSources = (sources ?? []).filter((source) => source.enabled).length;

  return (
    <div>
      {header}

      <div className="space-y-6">
        {/* Pipeline board */}
        <section aria-label="ไปป์ไลน์ลีด" className="space-y-3">
          <Card>
            <CardContent className="py-3">
              <LeadFilters kind={kind} minScore={minScore} q={q} />
            </CardContent>
          </Card>

          {!leadsPage ? (
            <Card>
              <CardContent>
                <p className="py-4 text-center text-sm text-slate-400">
                  API ยังไม่เชื่อมต่อ — แสดงไปป์ไลน์ลีดไม่ได้ ลองรีเฟรชหน้านี้อีกครั้ง
                </p>
              </CardContent>
            </Card>
          ) : leads.length === 0 ? (
            <Card>
              <CardContent>
                <div className="flex flex-col items-center py-8 text-center">
                  <UserSearch size={22} className="text-slate-300" />
                  <p className="mt-2 text-sm text-slate-400">
                    {hasFilter
                      ? "ไม่พบลีดตามเงื่อนไขที่เลือก — ลองปรับตัวกรองหรือล้างคำค้นหา"
                      : "ยังไม่มีลีดในระบบ — เพิ่มแหล่งค้นหาลูกค้าด้านล่างแล้วกด เก็บข้อมูลตอนนี้"}
                  </p>
                </div>
              </CardContent>
            </Card>
          ) : (
            <div className="overflow-x-auto pb-2">
              <div className="flex min-w-max gap-3">
                {STAGES.map((stage) => (
                  <StageColumn key={stage} stage={stage} leads={byStage(stage)} />
                ))}
              </div>
            </div>
          )}
          {leadsPage?.next_cursor && (
            <p className="text-xs text-slate-400">
              แสดง {formatNumber(leads.length)} รายการแรก — ใช้ตัวกรองหรือค้นหาเพื่อดูรายการที่เหลือ
            </p>
          )}
        </section>

        {/* Lead sources */}
        <section aria-label="แหล่งค้นหาลูกค้า" className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-semibold text-slate-900">แหล่งค้นหาลูกค้า</h2>
            {sources && (
              <Badge variant="blue">
                เปิดใช้งาน {formatNumber(enabledSources)}/{formatNumber(sources.length)} แหล่ง
              </Badge>
            )}
          </div>

          <Card>
            <CardHeader
              title="เพิ่มแหล่งค้นหาลูกค้า"
              subtitle="Reddit (subreddit + คำค้นหา) หรือฟีด RSS — ระบบตรวจนโยบายแหล่งข้อมูลให้อัตโนมัติ"
            />
            <CardContent>
              <LeadSourceCreateForm />
            </CardContent>
          </Card>

          {!sources ? (
            <Card>
              <CardContent>
                <p className="py-4 text-center text-sm text-slate-400">
                  API ยังไม่เชื่อมต่อ — แสดงแหล่งค้นหาลูกค้าไม่ได้
                </p>
              </CardContent>
            </Card>
          ) : sources.length === 0 ? (
            <Card>
              <CardContent>
                <p className="py-4 text-center text-sm text-slate-400">
                  ยังไม่มีแหล่งค้นหาลูกค้า — เพิ่ม subreddit หรือฟีด RSS ด้านบนเพื่อเริ่มเก็บลีด
                </p>
              </CardContent>
            </Card>
          ) : (
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {sources.map((source) => (
                <SourceCard key={source.id} source={source} />
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
