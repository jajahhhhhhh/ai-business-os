import type { Metadata } from "next";
import { ExternalLink } from "lucide-react";
import { ChangeFeed } from "@/components/competitors/ChangeFeed";
import { CompetitorActiveToggle } from "@/components/competitors/CompetitorActiveToggle";
import { CompetitorCreateForm } from "@/components/competitors/CompetitorCreateForm";
import { SourceCreateForm } from "@/components/competitors/SourceCreateForm";
import { SourceEnabledToggle } from "@/components/competitors/SourceEnabledToggle";
import { SweepButton } from "@/components/competitors/SweepButton";
import { WeeklyReportButton } from "@/components/competitors/WeeklyReportButton";
import { DataTable } from "@/components/DataTable";
import type { Column } from "@/components/DataTable";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/Badge";
import type { BadgeVariant } from "@/components/ui/Badge";
import { Card, CardContent, CardHeader } from "@/components/ui/Card";
import { listChangeEvents, listCompetitors, listSources, safe } from "@/lib/api";
import { formatDateTimeTH, formatNumber, formatRelativeTH } from "@/lib/format";
import { competitorKindLabel, SOURCE_STATUS_LABELS, SOURCE_TYPE_LABELS } from "@/lib/i18n";
import type { Competitor, Source, SourceFetchStatus } from "@/lib/types";

export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "คู่แข่ง" };

const FEED_LIMIT = 50;

const SOURCE_STATUS_BADGE: Record<SourceFetchStatus, BadgeVariant> = {
  ok: "green",
  unchanged: "neutral",
  changed: "blue",
  refused: "amber",
  error: "red",
};

/** Hostname + path without the scheme — keeps long URLs scannable in a cell. */
function displayUrl(url: string): string {
  return url.replace(/^https?:\/\//, "").replace(/\/$/, "");
}

const COMPETITOR_COLUMNS: Column<Competitor>[] = [
  {
    key: "name",
    header: "คู่แข่ง",
    render: (competitor) => (
      <div className="min-w-0 max-w-[16rem]">
        <p className="truncate font-medium text-slate-900">{competitor.name}</p>
        {competitor.website ? (
          <a
            href={competitor.website}
            target="_blank"
            rel="noopener noreferrer"
            title={competitor.website}
            className="mt-0.5 inline-flex max-w-full items-center gap-1 text-xs text-slate-400 transition-colors hover:text-blue-600"
          >
            <span className="truncate">{displayUrl(competitor.website)}</span>
            <ExternalLink size={12} className="shrink-0" />
          </a>
        ) : (
          <p className="mt-0.5 text-xs text-slate-300">ไม่มีเว็บไซต์</p>
        )}
      </div>
    ),
  },
  {
    key: "kind",
    header: "ประเภท",
    render: (competitor) => (
      <Badge variant="outline">{competitorKindLabel(competitor.kind)}</Badge>
    ),
  },
  {
    key: "sources",
    header: "แหล่งข้อมูล",
    render: (competitor) => (
      <span className="whitespace-nowrap text-slate-500">
        {formatNumber(competitor.sources_count)} แหล่งข้อมูล
      </span>
    ),
  },
  {
    key: "last_change",
    header: "เปลี่ยนแปลงล่าสุด",
    render: (competitor) => (
      <span
        className="whitespace-nowrap text-slate-500"
        title={
          competitor.last_change_at ? formatDateTimeTH(competitor.last_change_at) : undefined
        }
      >
        {competitor.last_change_at
          ? formatRelativeTH(competitor.last_change_at)
          : "ยังไม่พบ"}
      </span>
    ),
  },
  {
    key: "active",
    header: "ติดตาม",
    render: (competitor) => (
      <CompetitorActiveToggle
        competitorId={competitor.id}
        active={competitor.active}
        name={competitor.name}
      />
    ),
  },
  {
    key: "actions",
    header: "",
    render: (competitor) => <SweepButton competitorId={competitor.id} />,
  },
];

const SOURCE_COLUMNS: Column<Source>[] = [
  {
    key: "name",
    header: "แหล่งข้อมูล",
    render: (source) => (
      <div className="min-w-0 max-w-[16rem]">
        <p className="truncate font-medium text-slate-900">{source.name}</p>
        <a
          href={source.url}
          target="_blank"
          rel="noopener noreferrer"
          title={source.url}
          className="mt-0.5 inline-flex max-w-full items-center gap-1 text-xs text-slate-400 transition-colors hover:text-blue-600"
        >
          <span className="truncate">{displayUrl(source.url)}</span>
          <ExternalLink size={12} className="shrink-0" />
        </a>
      </div>
    ),
  },
  {
    key: "type",
    header: "ประเภท",
    render: (source) => <Badge variant="outline">{SOURCE_TYPE_LABELS[source.type].th}</Badge>,
  },
  {
    key: "competitor",
    header: "คู่แข่ง",
    render: (source) => (
      <span className="whitespace-nowrap text-slate-500">
        {source.competitor_name ?? "ไม่ระบุ"}
      </span>
    ),
  },
  {
    key: "last_status",
    header: "ผลการดึงล่าสุด",
    render: (source) => (
      <div>
        {source.last_status ? (
          <Badge variant={SOURCE_STATUS_BADGE[source.last_status]}>
            {SOURCE_STATUS_LABELS[source.last_status].th}
          </Badge>
        ) : (
          <Badge variant="outline">ยังไม่เคยดึง</Badge>
        )}
        <p className="mt-1 whitespace-nowrap text-xs text-slate-400">
          {formatDateTimeTH(source.last_fetched_at)}
        </p>
      </div>
    ),
  },
  {
    key: "enabled",
    header: "เปิดใช้งาน",
    render: (source) => (
      <SourceEnabledToggle sourceId={source.id} enabled={source.enabled} name={source.name} />
    ),
  },
];

export default async function CompetitorsPage() {
  const [competitors, sources, events] = await Promise.all([
    safe(listCompetitors()),
    safe(listSources()),
    safe(listChangeEvents({ limit: FEED_LIMIT })),
  ]);

  const header = (
    <PageHeader
      title="คู่แข่ง"
      subtitle="ติดตามวิลล่าคู่แข่งย่าน Lipa Noi และ Chaweng · Competitors"
      action={<WeeklyReportButton />}
    />
  );

  // API fully unreachable → graceful fallback, never a crash.
  if (!competitors && !sources && !events) {
    return (
      <div>
        {header}
        <EmptyState />
      </div>
    );
  }

  const competitorOptions = (competitors ?? []).map(({ id, name }) => ({ id, name }));
  const activeCount = (competitors ?? []).filter((competitor) => competitor.active).length;

  return (
    <div>
      {header}

      <div className="space-y-6">
        {/* Competitor registry */}
        <Card>
          <CardHeader
            title="คู่แข่งที่ติดตาม"
            subtitle="Registry — เปิด/ปิดการติดตาม หรือสั่งสแกนได้ทันที"
            action={
              competitors ? (
                <Badge variant="blue">
                  ติดตามอยู่ {formatNumber(activeCount)}/{formatNumber(competitors.length)} ราย
                </Badge>
              ) : undefined
            }
          />
          <CardContent className="space-y-4">
            {competitors ? (
              <DataTable
                columns={COMPETITOR_COLUMNS}
                rows={competitors}
                rowKey={(competitor) => competitor.id}
                emptyText="ยังไม่มีคู่แข่งในระบบ — เพิ่มวิลล่าคู่แข่งรายแรกด้านล่างเพื่อเริ่มติดตาม"
              />
            ) : (
              <p className="py-4 text-center text-sm text-slate-400">
                API ยังไม่เชื่อมต่อ — แสดงทะเบียนคู่แข่งไม่ได้
              </p>
            )}
            <CompetitorCreateForm />
          </CardContent>
        </Card>

        {/* Sources */}
        <Card>
          <CardHeader
            title="แหล่งข้อมูล"
            subtitle="Sources — ทุก URL ผ่านนโยบาย ToS ก่อนเพิ่ม (compliance gate บังคับในโค้ด)"
            action={
              sources ? (
                <Badge variant="blue">{formatNumber(sources.length)} แหล่ง</Badge>
              ) : undefined
            }
          />
          <CardContent className="space-y-4">
            {sources ? (
              <DataTable
                columns={SOURCE_COLUMNS}
                rows={sources}
                rowKey={(source) => source.id}
                emptyText="ยังไม่มีแหล่งข้อมูล — เพิ่มเว็บไซต์หรือฟีดของคู่แข่งด้านล่าง"
              />
            ) : (
              <p className="py-4 text-center text-sm text-slate-400">
                API ยังไม่เชื่อมต่อ — แสดงแหล่งข้อมูลไม่ได้
              </p>
            )}
            <SourceCreateForm competitors={competitorOptions} />
          </CardContent>
        </Card>

        {/* Change feed */}
        <ChangeFeed initialEvents={events} competitors={competitorOptions} />
      </div>
    </div>
  );
}
