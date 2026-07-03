import type { Metadata } from "next";
import {
  File,
  FileText,
  FileType,
  Image as ImageIcon,
  ScanText,
  Sparkles,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { DataTable } from "@/components/DataTable";
import type { Column } from "@/components/DataTable";
import { EmptyState } from "@/components/EmptyState";
import { KbRefreshButton } from "@/components/kb/KbRefreshButton";
import { KbSearch } from "@/components/kb/KbSearch";
import { KbUploadForm } from "@/components/kb/KbUploadForm";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/Badge";
import type { BadgeVariant } from "@/components/ui/Badge";
import { Card, CardContent, CardHeader } from "@/components/ui/Card";
import { listKbDocuments, safe } from "@/lib/api";
import { formatBytes, formatDateTimeTH } from "@/lib/format";
import { KB_DOC_STATUS_LABELS } from "@/lib/i18n";
import type { KbDocument, KbDocumentStatus } from "@/lib/types";

export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "คลังความรู้" };

const DOCUMENT_LIMIT = 50;

const STATUS_BADGE: Record<KbDocumentStatus, BadgeVariant> = {
  pending: "neutral",
  parsing: "blue",
  indexed: "green",
  failed: "red",
};

function mimeIcon(mime: string): LucideIcon {
  if (mime === "application/pdf") return FileText;
  if (mime.startsWith("image/")) return ImageIcon;
  if (mime.startsWith("text/")) return FileType;
  return File;
}

/** Small done/not-done pipeline indicator (OCR, vector embedding). */
function StageIndicator({
  icon: Icon,
  label,
  done,
}: {
  icon: LucideIcon;
  label: string;
  done: boolean;
}) {
  return (
    <span
      title={done ? `${label} — เสร็จแล้ว` : `${label} — ยังไม่เสร็จ`}
      className={`inline-flex items-center gap-1 text-xs ${
        done ? "text-emerald-600" : "text-slate-300"
      }`}
    >
      <Icon size={13} />
      {label}
    </span>
  );
}

const COLUMNS: Column<KbDocument>[] = [
  {
    key: "title",
    header: "เอกสาร",
    render: (doc) => {
      const Icon = mimeIcon(doc.mime);
      return (
        <div className="flex items-start gap-2.5">
          <span className="mt-0.5 shrink-0 rounded-lg bg-slate-100 p-1.5 text-slate-500">
            <Icon size={15} />
          </span>
          <div className="min-w-0">
            <p className="font-medium text-slate-900">{doc.title}</p>
            <p className="text-xs text-slate-400">
              {doc.mime}
              {doc.lang ? ` · ${doc.lang === "th" ? "ไทย" : doc.lang.toUpperCase()}` : ""}
            </p>
            {doc.status === "failed" && doc.error && (
              <p
                title={doc.error}
                className="mt-0.5 max-w-[18rem] truncate text-xs text-rose-600"
              >
                {doc.error}
              </p>
            )}
          </div>
        </div>
      );
    },
  },
  {
    key: "size",
    header: "ขนาด",
    align: "right",
    render: (doc) => (
      <span className="whitespace-nowrap text-slate-500">{formatBytes(doc.size_bytes)}</span>
    ),
  },
  {
    key: "status",
    header: "สถานะ",
    render: (doc) => (
      <div>
        <Badge variant={STATUS_BADGE[doc.status]}>
          {KB_DOC_STATUS_LABELS[doc.status].th}
        </Badge>
        {(doc.status === "pending" || doc.status === "parsing") && (
          <p className="mt-1 whitespace-nowrap text-xs text-amber-600">
            กด รีเฟรช เพื่ออัปเดตสถานะ
          </p>
        )}
      </div>
    ),
  },
  {
    key: "stages",
    header: "การประมวลผล",
    render: (doc) => (
      <div className="flex flex-col gap-1">
        <StageIndicator icon={ScanText} label="OCR" done={doc.ocr_done} />
        <StageIndicator icon={Sparkles} label="ฝังเวกเตอร์" done={doc.embedded} />
      </div>
    ),
  },
  {
    key: "created_at",
    header: "อัปโหลดเมื่อ",
    render: (doc) => (
      <span className="whitespace-nowrap text-slate-500">
        {formatDateTimeTH(doc.created_at)}
      </span>
    ),
  },
];

export default async function KnowledgeBasePage() {
  const documents = await safe(listKbDocuments({ limit: DOCUMENT_LIMIT }));

  return (
    <div>
      <PageHeader
        title="คลังความรู้"
        subtitle="ค้นหาเอกสาร ใบเสนอราคา สัญญา และอีเมลทั้งหมด · Knowledge Base"
      />

      <div className="space-y-6">
        {/* Hybrid search — client-side, calls GET /v1/kb/search on submit. */}
        <KbSearch />

        <Card>
          <CardHeader
            title="อัปโหลดเอกสาร"
            subtitle="ไฟล์จะถูกอ่าน (OCR ถ้าเป็นรูป/สแกน) แล้วจัดทำดัชนีให้ค้นหาได้อัตโนมัติ"
          />
          <CardContent>
            <KbUploadForm />
          </CardContent>
        </Card>

        {documents === null ? (
          <EmptyState />
        ) : (
          <Card>
            <CardHeader
              title="เอกสารล่าสุด"
              subtitle="เรียงจากรายการล่าสุด"
              action={
                <div className="flex items-center gap-2">
                  <Badge variant="blue">{documents.length} รายการ</Badge>
                  <KbRefreshButton />
                </div>
              }
            />
            <CardContent>
              <DataTable
                columns={COLUMNS}
                rows={documents}
                rowKey={(doc) => doc.id}
                emptyText="ยังไม่มีเอกสารในคลัง — อัปโหลดไฟล์แรกด้านบนเพื่อเริ่มต้น"
              />
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
