/**
 * Thai/English string table — Thai is the default UI language (owner locale).
 * The topbar locale toggle is visual-only for now; full locale routing lands
 * with the i18n middleware in M2.
 */

import type {
  AgentRunStatus,
  ChangeSeverity,
  DrawStatus,
  LeadKind,
  LeadStage,
  MilestoneStatus,
  ReportKind,
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

export const DRAW_STATUS_LABELS: Record<DrawStatus, LocalizedText> = {
  requested: { th: "ขอเบิก", en: "Requested" },
  approved: { th: "อนุมัติแล้ว", en: "Approved" },
  paid: { th: "จ่ายแล้ว", en: "Paid" },
  rejected: { th: "ตีกลับ", en: "Rejected" },
};

export const MILESTONE_STATUS_LABELS: Record<MilestoneStatus, LocalizedText> = {
  planned: { th: "รอเริ่ม", en: "Planned" },
  in_progress: { th: "กำลังทำ", en: "In progress" },
  done: { th: "เสร็จแล้ว", en: "Done" },
  delayed: { th: "ล่าช้า", en: "Delayed" },
};

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

const CATEGORY_LABELS: Record<string, LocalizedText> = {
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
  const entry = CATEGORY_LABELS[category.toLowerCase()];
  return entry ? entry[locale] : category;
}
