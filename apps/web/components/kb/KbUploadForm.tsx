"use client";

import { useRef, useState } from "react";
import type { ChangeEvent, FormEvent } from "react";
import { CheckCircle2, Upload } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { FormError } from "@/components/ui/FormError";
import { Input, Select } from "@/components/ui/Input";
import { uploadKbDocument } from "@/lib/api";
import { KB_DOC_STATUS_LABELS } from "@/lib/i18n";
import type { KbDocument, KbLang } from "@/lib/types";
import { useApiAction } from "@/lib/useApiAction";

const ACCEPT = ".pdf,.png,.jpg,.jpeg,.txt,.md";
const MAX_SIZE_BYTES = 25 * 1024 * 1024;

/** "" = ให้ระบบเดาภาษาเอง (omit the field from the form data). */
type LangChoice = "" | KbLang;

/**
 * Upload form → POST /v1/kb/documents (multipart). Success shows the 202
 * status; useApiAction refreshes the server-rendered document list below.
 */
export function KbUploadForm() {
  const { run, pending, error, clearError } = useApiAction();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [lang, setLang] = useState<LangChoice>("");
  const [sizeError, setSizeError] = useState<string | null>(null);
  const [uploaded, setUploaded] = useState<KbDocument | null>(null);

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    setFile(event.target.files?.[0] ?? null);
    setSizeError(null);
    setUploaded(null);
    clearError();
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file || pending) return;

    // Pre-check the 25 MB cap so we can fail fast without burning upstream —
    // the API still enforces it (413) as the source of truth.
    if (file.size > MAX_SIZE_BYTES) {
      setSizeError("ไฟล์ใหญ่เกิน 25 MB — ลดขนาดไฟล์แล้วลองอีกครั้ง");
      return;
    }

    setSizeError(null);
    setUploaded(null);
    const document = await run(() =>
      uploadKbDocument({
        file,
        title: title.trim() || undefined,
        lang: lang === "" ? undefined : lang,
      }),
    );
    if (document) {
      setUploaded(document);
      setFile(null);
      setTitle("");
      setLang("");
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
        <input
          ref={fileInputRef}
          type="file"
          accept={ACCEPT}
          onChange={handleFileChange}
          aria-label="เลือกไฟล์เอกสาร"
          className="min-w-0 flex-1 text-sm text-slate-500 file:mr-3 file:cursor-pointer file:rounded-xl file:border-0 file:bg-blue-50 file:px-4 file:py-2 file:text-sm file:font-medium file:text-blue-700 hover:file:bg-blue-100"
        />
        <Input
          type="text"
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder="ชื่อเอกสาร (ไม่บังคับ)"
          aria-label="ชื่อเอกสาร"
          className="lg:w-64"
        />
        <Select
          value={lang}
          onChange={(event) => setLang(event.target.value as LangChoice)}
          aria-label="ภาษาของเอกสาร"
          className="lg:w-40"
        >
          <option value="">ภาษา: อัตโนมัติ</option>
          <option value="th">ภาษา: ไทย</option>
          <option value="en">ภาษา: EN</option>
        </Select>
        <Button type="submit" disabled={pending || !file}>
          <Upload size={16} />
          {pending ? "กำลังอัปโหลด..." : "อัปโหลด"}
        </Button>
      </div>

      <FormError error={error ?? sizeError} />

      {uploaded && (
        <div className="flex flex-wrap items-center gap-2 rounded-xl bg-emerald-50 px-3 py-2.5 text-sm text-emerald-800">
          <CheckCircle2 size={16} className="shrink-0" />
          <span>รับไฟล์ &ldquo;{uploaded.title}&rdquo; แล้ว</span>
          <Badge variant={uploaded.status === "failed" ? "red" : "blue"}>
            {KB_DOC_STATUS_LABELS[uploaded.status].th}
          </Badge>
          <span className="text-xs text-emerald-700">
            ระบบกำลังอ่านและจัดทำดัชนี — กด รีเฟรช ที่รายการด้านล่างเพื่อดูสถานะล่าสุด
          </span>
        </div>
      )}

      <p className="text-xs text-slate-400">
        รองรับ PDF, รูปภาพ (OCR ภาษาไทย), ไฟล์ข้อความ — สูงสุด 25 MB
      </p>
    </form>
  );
}
