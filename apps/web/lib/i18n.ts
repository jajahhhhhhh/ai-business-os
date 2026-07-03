/**
 * Thai/English string table — Thai is the default UI language (owner locale).
 * The topbar locale toggle is visual-only for now; full locale routing lands
 * with the i18n middleware in M2.
 */

import type {
  AgentRunStatus,
  BankTransactionDirection,
  BankTransactionStatus,
  ChangeCategory,
  ChangeSeverity,
  CompetitorKind,
  DrawRowStatus,
  DrawStatus,
  KbDocumentStatus,
  KbSearchMode,
  LeadKind,
  LeadStage,
  MilestoneStatus,
  ReportKind,
  SourceFetchStatus,
  SourceType,
} from "./types";

export type Locale = "th" | "en";

export const DEFAULT_LOCALE: Locale = "th";

export interface LocalizedText {
  th: string;
  en: string;
}

const messages = {
  "app.title": { th: "AI Business OS", en: "AI Business OS" },
  "app.brand": { th: "howtoniksen.com", en: "howtoniksen.com" },
  "common.searchPlaceholder": { th: "ค้นหา...", en: "Search..." },
  "common.viewAll": { th: "ดูทั้งหมด", en: "View all" },
  "common.noData": { th: "ไม่มีข้อมูล", en: "No data" },
  "common.apiOffline.title": { th: "API ยังไม่เชื่อมต่อ", en: "API not connected" },
  "common.apiOffline.description": {
    th: "เชื่อมต่อเซิร์ฟเวอร์ FastAPI ไม่ได้ในขณะนี้ — เริ่มเซิร์ฟเวอร์แล้วรีเฟรชหน้านี้อีกครั้ง (ค่าเริ่มต้น http://localhost:8000)",
    en: "Cannot reach the FastAPI server — start it and refresh this page (default http://localhost:8000)",
  },
} as const satisfies Record<string, LocalizedText>;

export type MessageKey = keyof typeof messages;

export function t(key: MessageKey, locale: Locale = DEFAULT_LOCALE): string {
  return messages[key][locale];
}

// ---------------------------------------------------------------------------
// Domain label maps (Thai primary, English secondary)
// ---------------------------------------------------------------------------

export const LEAD_STAGE_LABELS: Record<LeadStage, LocalizedText> = {
  discovered: { th: "ค้นพบใหม่", en: "Discovered" },
  qualified: { th: "คัดกรองแล้ว", en: "Qualified" },
  contacted: { th: "ติดต่อแล้ว", en: "Contacted" },
  won: { th: "ปิดดีลได้", en: "Won" },
  lost: { th: "พลาดไป", en: "Lost" },
};

export const LEAD_KIND_LABELS: Record<LeadKind, LocalizedText> = {
  guest: { th: "นักท่องเที่ยว", en: "Guest" },
  longstay: { th: "พักระยะยาว", en: "Long-stay" },
  b2b: { th: "ธุรกิจ (B2B)", en: "B2B" },
  supplier: { th: "ซัพพลายเออร์", en: "Supplier" },
};

export const SEVERITY_LABELS: Record<ChangeSeverity, LocalizedText> = {
  low: { th: "ต่ำ", en: "Low" },
  medium: { th: "ปานกลาง", en: "Medium" },
  high: { th: "สูง", en: "High" },
  critical: { th: "วิกฤต", en: "Critical" },
};

/** Change-event categories — `baseline` = first snapshot of a competitor. */
export const CHANGE_CATEGORY_LABELS: Record<ChangeCategory, LocalizedText> = {
  baseline: { th: "เริ่มติดตาม", en: "Baseline" },
  pricing: { th: "ราคา", en: "Pricing" },
  promotion: { th: "โปรโมชัน", en: "Promotion" },
  content: { th: "เนื้อหา", en: "Content" },
  availability: { th: "ห้องว่าง", en: "Availability" },
  reviews: { th: "รีวิว", en: "Reviews" },
  other: { th: "อื่น ๆ", en: "Other" },
};

export const SOURCE_TYPE_LABELS: Record<SourceType, LocalizedText> = {
  website: { th: "เว็บไซต์", en: "Website" },
  rss: { th: "RSS", en: "RSS" },
  sitemap: { th: "แผนผังเว็บ", en: "Sitemap" },
};

/** Outcome of the collector's last fetch of a source. */
export const SOURCE_STATUS_LABELS: Record<SourceFetchStatus, LocalizedText> = {
  ok: { th: "ปกติ", en: "OK" },
  unchanged: { th: "ไม่เปลี่ยนแปลง", en: "Unchanged" },
  changed: { th: "พบการเปลี่ยนแปลง", en: "Changed" },
  refused: { th: "ถูกปฏิเสธ", en: "Refused" },
  error: { th: "ผิดพลาด", en: "Error" },
};

/** Competitor kinds offered by the create form (API stores a free string). */
export const COMPETITOR_KIND_LABELS: Record<CompetitorKind, LocalizedText> = {
  villa: { th: "วิลล่า", en: "Villa" },
  hotel: { th: "โรงแรม", en: "Hotel" },
  aspirational: { th: "แบรนด์ต้นแบบ", en: "Aspirational brand" },
  other: { th: "อื่น ๆ", en: "Other" },
};

function isCompetitorKind(value: string): value is CompetitorKind {
  return value in COMPETITOR_KIND_LABELS;
}

/** Thai label for a competitor kind (free string, nullable); falls back to the raw value. */
export function competitorKindLabel(
  kind: string | null,
  locale: Locale = DEFAULT_LOCALE,
): string {
  if (!kind) return locale === "th" ? "ไม่ระบุ" : "Unspecified";
  const slug = kind.toLowerCase();
  return isCompetitorKind(slug) ? COMPETITOR_KIND_LABELS[slug][locale] : kind;
}

export const DRAW_STATUS_LABELS: Record<DrawStatus, LocalizedText> = {
  requested: { th: "ขอเบิก", en: "Requested" },
  approved: { th: "อนุมัติแล้ว", en: "Approved" },
  paid: { th: "จ่ายแล้ว", en: "Paid" },
  rejected: { th: "ตีกลับ", en: "Rejected" },
};

/** Status vocabulary of GET /v1/renovation/draws (backend domain model). */
export const DRAW_ROW_STATUS_LABELS: Record<DrawRowStatus, LocalizedText> = {
  pending: { th: "รอจ่าย", en: "Pending" },
  paid: { th: "จ่ายแล้ว", en: "Paid" },
  cancelled: { th: "ยกเลิก", en: "Cancelled" },
};

const QUOTATION_STATUS_LABELS: Record<string, LocalizedText> = {
  pending: { th: "รออนุมัติ", en: "Pending" },
  approved: { th: "อนุมัติแล้ว", en: "Approved" },
  rejected: { th: "ไม่อนุมัติ", en: "Rejected" },
};

/** Thai label for a quotation status; falls back to the raw value. */
export function quotationStatusLabel(status: string, locale: Locale = DEFAULT_LOCALE): string {
  const entry = QUOTATION_STATUS_LABELS[status.toLowerCase()];
  return entry ? entry[locale] : status;
}

export const BANK_TX_STATUS_LABELS: Record<BankTransactionStatus, LocalizedText> = {
  unmatched: { th: "รอจับคู่", en: "Unmatched" },
  matched: { th: "จับคู่แล้ว", en: "Matched" },
  confirmed: { th: "ยืนยันแล้ว", en: "Confirmed" },
  ignored: { th: "ไม่เกี่ยวข้อง", en: "Ignored" },
};

export const BANK_TX_DIRECTION_LABELS: Record<BankTransactionDirection, LocalizedText> = {
  in: { th: "เข้า", en: "In" },
  out: { th: "ออก", en: "Out" },
};

export const MILESTONE_STATUS_LABELS: Record<MilestoneStatus, LocalizedText> = {
  planned: { th: "รอเริ่ม", en: "Planned" },
  in_progress: { th: "กำลังทำ", en: "In progress" },
  done: { th: "เสร็จแล้ว", en: "Done" },
  delayed: { th: "ล่าช้า", en: "Delayed" },
};

export const KB_DOC_STATUS_LABELS: Record<KbDocumentStatus, LocalizedText> = {
  pending: { th: "รอประมวลผล", en: "Pending" },
  parsing: { th: "กำลังอ่าน", en: "Parsing" },
  indexed: { th: "พร้อมค้นหา", en: "Ready" },
  failed: { th: "ล้มเหลว", en: "Failed" },
};

export const KB_SEARCH_MODE_LABELS: Record<KbSearchMode, LocalizedText> = {
  hybrid: { th: "ไฮบริด", en: "Hybrid" },
  keyword: { th: "คีย์เวิร์ด", en: "Keyword" },
  semantic: { th: "ความหมาย", en: "Semantic" },
};

const KB_MATCHED_BY_LABELS: Record<string, LocalizedText> = {
  keyword: { th: "คีย์เวิร์ด", en: "Keyword" },
  vector: { th: "เวกเตอร์", en: "Vector" },
  semantic: { th: "เวกเตอร์", en: "Vector" },
};

/** Thai label for a search-result matched_by value; falls back to the raw value. */
export function kbMatchedByLabel(value: string, locale: Locale = DEFAULT_LOCALE): string {
  const entry = KB_MATCHED_BY_LABELS[value.toLowerCase()];
  return entry ? entry[locale] : value;
}

export const RUN_STATUS_LABELS: Record<AgentRunStatus, LocalizedText> = {
  queued: { th: "รอคิว", en: "Queued" },
  running: { th: "กำลังทำงาน", en: "Running" },
  succeeded: { th: "สำเร็จ", en: "Succeeded" },
  failed: { th: "ล้มเหลว", en: "Failed" },
};

export const REPORT_KIND_LABELS: Record<ReportKind, LocalizedText> = {
  daily: { th: "รายวัน", en: "Daily" },
  weekly: { th: "รายสัปดาห์", en: "Weekly" },
  monthly: { th: "รายเดือน", en: "Monthly" },
};

/** Spend-category slugs → labels; exported for the quotation-form select. */
export const SPEND_CATEGORY_LABELS: Record<string, LocalizedText> = {
  electrical: { th: "งานไฟฟ้า", en: "Electrical" },
  plumbing: { th: "งานประปา", en: "Plumbing" },
  demolition: { th: "งานรื้อถอน", en: "Demolition" },
  structure: { th: "งานโครงสร้าง", en: "Structure" },
  finishing: { th: "งานตกแต่ง", en: "Finishing" },
  pool: { th: "งานสระว่ายน้ำ", en: "Pool" },
  landscape: { th: "งานภูมิทัศน์", en: "Landscape" },
  furniture: { th: "เฟอร์นิเจอร์", en: "Furniture" },
  other: { th: "อื่น ๆ", en: "Other" },
};

/** Thai label for a spend category slug; falls back to the raw slug. */
export function categoryLabel(category: string, locale: Locale = DEFAULT_LOCALE): string {
  const entry = SPEND_CATEGORY_LABELS[category.toLowerCase()];
  return entry ? entry[locale] : category;
}
