/**
 * THB currency + Thai date formatting via Intl (locale th-TH, Buddhist calendar
 * for dates — natural for the Thai owner).
 */

const THB_FULL = new Intl.NumberFormat("th-TH", {
  style: "currency",
  currency: "THB",
  maximumFractionDigits: 0,
});

const THB_COMPACT = new Intl.NumberFormat("th-TH", {
  style: "currency",
  currency: "THB",
  notation: "compact",
  maximumFractionDigits: 2,
});

const USD = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 4,
});

const NUMBER_TH = new Intl.NumberFormat("th-TH");

const DATE_SHORT = new Intl.DateTimeFormat("th-TH", {
  day: "numeric",
  month: "short",
  year: "2-digit",
});

const DATE_TIME = new Intl.DateTimeFormat("th-TH", {
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
});

function parseDate(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** ฿1,234,567 */
export function formatTHB(amount: number): string {
  return THB_FULL.format(amount);
}

/** ฿1.2 ล้าน — for tight stat cards. */
export function formatTHBCompact(amount: number): string {
  return THB_COMPACT.format(amount);
}

/** $0.0432 — agent LLM cost. */
export function formatUSD(amount: number): string {
  return USD.format(amount);
}

/** 12,345 with th-TH grouping. */
export function formatNumber(value: number): string {
  return NUMBER_TH.format(value);
}

/** e.g. "3 ก.ค. 69" (Buddhist calendar year). */
export function formatDateTH(iso: string | null | undefined): string {
  const date = parseDate(iso);
  return date ? DATE_SHORT.format(date) : "—";
}

/** e.g. "3 ก.ค. 07:30" */
export function formatDateTimeTH(iso: string | null | undefined): string {
  const date = parseDate(iso);
  return date ? DATE_TIME.format(date) : "—";
}

const RELATIVE_TH = new Intl.RelativeTimeFormat("th-TH", { numeric: "always" });

/**
 * Thai relative time for recent events, e.g. "5 นาทีที่ผ่านมา" / "3 ชั่วโมงที่ผ่านมา";
 * beyond 7 days falls back to the short Buddhist-calendar date. null → "—".
 */
export function formatRelativeTH(iso: string | null | undefined): string {
  const date = parseDate(iso);
  if (!date) return "—";
  const minutes = Math.round((Date.now() - date.getTime()) / 60_000);
  if (minutes < 1) return "เมื่อสักครู่";
  if (minutes < 60) return RELATIVE_TH.format(-minutes, "minute");
  const hours = Math.round(minutes / 60);
  if (hours < 24) return RELATIVE_TH.format(-hours, "hour");
  const days = Math.round(hours / 24);
  if (days <= 7) return RELATIVE_TH.format(-days, "day");
  return DATE_SHORT.format(date);
}

/** File size in B / KB / MB, e.g. "812 KB", "2.4 MB"; null → "—". */
export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined || bytes < 0) return "—";
  if (bytes < 1024) return `${bytes} B`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${NUMBER_TH.format(Math.round(kb))} KB`;
  const mb = kb / 1024;
  return `${mb >= 10 ? Math.round(mb) : mb.toFixed(1)} MB`;
}

/** Integer percentage of value/total, clamped to [0, 999]. */
export function percentOf(value: number, total: number): number {
  if (total <= 0) return 0;
  return Math.min(Math.round((value / total) * 100), 999);
}

/** Run duration in Thai, e.g. "42 วิ" / "3 นาที 5 วิ". */
export function formatDurationTH(startIso: string, endIso: string | null): string {
  if (!endIso) return "กำลังทำงาน";
  const start = parseDate(startIso);
  const end = parseDate(endIso);
  if (!start || !end) return "—";
  const seconds = Math.round((end.getTime() - start.getTime()) / 1000);
  if (seconds < 0) return "—";
  if (seconds < 60) return `${seconds} วิ`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes} นาที ${seconds % 60} วิ`;
}
