"use client";

import { useState } from "react";
import { Loader2, Radar } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import type { BadgeVariant } from "@/components/ui/Badge";
import { Card, CardContent, CardHeader } from "@/components/ui/Card";
import { Select } from "@/components/ui/Input";
import { ApiError, listChangeEvents } from "@/lib/api";
import { formatDateTimeTH, formatNumber } from "@/lib/format";
import { CHANGE_CATEGORY_LABELS, SEVERITY_LABELS } from "@/lib/i18n";
import type { ChangeEventRow, ChangeSeverity } from "@/lib/types";

const FEED_LIMIT = 50;
const NETWORK_ERROR_TH =
  "เชื่อมต่อเซิร์ฟเวอร์ไม่ได้ — ตรวจสอบว่า API ทำงานอยู่แล้วลองอีกครั้ง";

/** Severity chips in urgency order; "" = ทั้งหมด (no filter). */
const SEVERITY_CHIPS: ChangeSeverity[] = ["critical", "high", "medium", "low"];

const SEVERITY_BADGE: Record<ChangeSeverity, BadgeVariant> = {
  critical: "red",
  high: "orange",
  medium: "amber",
  low: "neutral",
};

/** Serializable competitor option built by the server page. */
export interface FeedCompetitorOption {
  id: string;
  name: string;
}

/**
 * Change feed with severity chips + competitor filter. The server page
 * provides the initial unfiltered page via safe(); changing a filter
 * re-fetches GET /v1/change-events client-side (same live-filter feel as the
 * KB search page).
 */
export function ChangeFeed({
  initialEvents,
  competitors,
}: {
  /** null = API unreachable during server render. */
  initialEvents: ChangeEventRow[] | null;
  competitors: FeedCompetitorOption[];
}) {
  const [events, setEvents] = useState<ChangeEventRow[] | null>(initialEvents);
  const [severity, setSeverity] = useState<ChangeSeverity | "">("");
  const [competitorId, setCompetitorId] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function refetch(nextSeverity: ChangeSeverity | "", nextCompetitorId: string) {
    setLoading(true);
    setError(null);
    try {
      setEvents(
        await listChangeEvents({
          severity: nextSeverity === "" ? undefined : nextSeverity,
          competitor_id: nextCompetitorId === "" ? undefined : nextCompetitorId,
          limit: FEED_LIMIT,
        }),
      );
    } catch (err) {
      setError(
        err instanceof ApiError
          ? `โหลดฟีดไม่สำเร็จ (HTTP ${err.status}) — ลองอีกครั้ง`
          : NETWORK_ERROR_TH,
      );
    } finally {
      setLoading(false);
    }
  }

  function handleSeverity(next: ChangeSeverity | "") {
    setSeverity(next);
    void refetch(next, competitorId);
  }

  function handleCompetitor(next: string) {
    setCompetitorId(next);
    void refetch(severity, next);
  }

  const chipClass = (active: boolean) =>
    `rounded-full border px-3 py-1 text-xs font-medium transition-colors ${
      active
        ? "border-blue-200 bg-blue-50 text-blue-700"
        : "border-slate-200 bg-white text-slate-500 hover:bg-slate-50"
    }`;

  return (
    <Card>
      <CardHeader
        title="ฟีดความเคลื่อนไหว"
        subtitle="Change feed — เรียงจากรายการล่าสุด"
        action={
          events !== null ? (
            <Badge variant="blue">{formatNumber(events.length)} รายการ</Badge>
          ) : undefined
        }
      />

      <CardContent className="border-b border-slate-100 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex flex-wrap items-center gap-2" role="group" aria-label="กรองตามระดับ">
            <button
              type="button"
              aria-pressed={severity === ""}
              className={chipClass(severity === "")}
              onClick={() => handleSeverity("")}
            >
              ทั้งหมด
            </button>
            {SEVERITY_CHIPS.map((level) => (
              <button
                key={level}
                type="button"
                aria-pressed={severity === level}
                className={chipClass(severity === level)}
                onClick={() => handleSeverity(level)}
              >
                {SEVERITY_LABELS[level].th}
              </button>
            ))}
          </div>
          <Select
            aria-label="กรองตามคู่แข่ง"
            value={competitorId}
            onChange={(event) => handleCompetitor(event.target.value)}
            className="ml-auto w-48 px-2 py-1.5 text-xs"
          >
            <option value="">คู่แข่งทั้งหมด</option>
            {competitors.map((competitor) => (
              <option key={competitor.id} value={competitor.id}>
                {competitor.name}
              </option>
            ))}
          </Select>
        </div>
      </CardContent>

      {error && (
        <CardContent className="py-3">
          <p role="alert" className="rounded-xl bg-rose-50 px-3 py-2 text-xs text-rose-700">
            {error}
          </p>
        </CardContent>
      )}

      {loading ? (
        <CardContent>
          <p className="flex items-center justify-center gap-2 py-6 text-sm text-slate-400">
            <Loader2 size={16} className="animate-spin" />
            กำลังโหลดฟีด...
          </p>
        </CardContent>
      ) : events === null ? (
        <CardContent>
          <p className="py-6 text-center text-sm text-slate-400">
            API ยังไม่เชื่อมต่อ — แสดงฟีดความเคลื่อนไหวไม่ได้ ลองรีเฟรชหน้านี้อีกครั้ง
          </p>
        </CardContent>
      ) : events.length === 0 ? (
        <CardContent>
          <div className="flex flex-col items-center py-8 text-center">
            <Radar size={22} className="text-slate-300" />
            <p className="mt-2 text-sm text-slate-400">
              ยังไม่พบความเคลื่อนไหวตามเงื่อนไขนี้ — ระบบจะบันทึกเมื่อสแกนพบการเปลี่ยนแปลง
            </p>
          </div>
        </CardContent>
      ) : (
        <ul className="divide-y divide-slate-100">
          {events.map((event) => (
            <li key={event.id} className="px-5 py-4">
              <div className="flex items-start justify-between gap-3">
                <p className="text-sm leading-relaxed text-slate-800">{event.summary}</p>
                <Badge variant={SEVERITY_BADGE[event.severity]}>
                  {SEVERITY_LABELS[event.severity].th}
                </Badge>
              </div>
              <p className="mt-1.5 text-xs text-slate-400">
                {event.competitor_name} · {CHANGE_CATEGORY_LABELS[event.category].th} ·{" "}
                {formatDateTimeTH(event.detected_at)}
              </p>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
