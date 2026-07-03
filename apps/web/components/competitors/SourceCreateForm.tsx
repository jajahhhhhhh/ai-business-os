"use client";

import { useState } from "react";
import type { FormEvent } from "react";
import { useRouter } from "next/navigation";
import { Plus, ShieldAlert } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { FormError } from "@/components/ui/FormError";
import { Input, Select } from "@/components/ui/Input";
import { ApiError, createCompetitorSource } from "@/lib/api";
import { SOURCE_TYPE_LABELS } from "@/lib/i18n";
import type { CompetitorSourceType } from "@/lib/types";

const TYPE_OPTIONS: CompetitorSourceType[] = ["website", "rss"];

const NETWORK_ERROR_TH =
  "เชื่อมต่อเซิร์ฟเวอร์ไม่ได้ — ตรวจสอบว่า API ทำงานอยู่แล้วลองอีกครั้ง";

/**
 * Inline "เพิ่มแหล่งข้อมูล" mini-form on each competitor card —
 * POST /v1/competitors/{id}/sources.
 *
 * Does not use useApiAction because a 422 needs special treatment: it is the
 * ToS compliance gate refusing a blocked domain (Facebook / Airbnb / Booking /
 * Agoda) — its Thai detail is shown as a prominent policy panel.
 */
export function SourceCreateForm({ competitorId }: { competitorId: string }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  /** problem+json detail from the 422 ToS compliance gate. */
  const [blockedDetail, setBlockedDetail] = useState<string | null>(null);

  const [type, setType] = useState<CompetitorSourceType>("website");
  const [url, setUrl] = useState("");

  function handleTypeChange(value: string) {
    // The select only offers TYPE_OPTIONS values — validate instead of casting.
    const match = TYPE_OPTIONS.find((option) => option === value);
    if (match) setType(match);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedUrl = url.trim();
    if (trimmedUrl === "") return;

    setPending(true);
    setError(null);
    setBlockedDetail(null);
    try {
      await createCompetitorSource(competitorId, { type, url: trimmedUrl });
      router.refresh();
      setUrl("");
      setType("website");
      setOpen(false);
    } catch (err) {
      if (err instanceof ApiError && err.status === 422) {
        setBlockedDetail(err.message);
      } else {
        setError(err instanceof ApiError ? err.message : NETWORK_ERROR_TH);
      }
    } finally {
      setPending(false);
    }
  }

  if (!open) {
    return (
      <Button
        variant="ghost"
        className="px-2 py-1 text-xs"
        onClick={() => {
          setError(null);
          setBlockedDetail(null);
          setOpen(true);
        }}
      >
        <Plus size={13} />
        เพิ่มแหล่งข้อมูล
      </Button>
    );
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="space-y-2 rounded-xl border border-slate-200 bg-slate-50/60 p-3"
    >
      <div className="flex flex-wrap gap-2">
        <Select
          aria-label="ประเภทแหล่งข้อมูล"
          value={type}
          onChange={(event) => handleTypeChange(event.target.value)}
          className="w-28 px-2 py-1.5 text-xs"
        >
          {TYPE_OPTIONS.map((option) => (
            <option key={option} value={option}>
              {SOURCE_TYPE_LABELS[option].th}
            </option>
          ))}
        </Select>
        <Input
          required
          type="url"
          aria-label="URL แหล่งข้อมูล"
          value={url}
          onChange={(event) => setUrl(event.target.value)}
          placeholder="https://..."
          className="min-w-0 flex-1 px-2 py-1.5 text-xs"
        />
      </div>

      {blockedDetail && (
        <div
          role="alert"
          className="flex items-start gap-2 rounded-xl border border-amber-300 bg-amber-50 px-3 py-2"
        >
          <ShieldAlert size={14} className="mt-0.5 shrink-0 text-amber-600" />
          <div className="text-xs text-amber-900">
            <p className="font-semibold">แหล่งข้อมูลนี้ถูกปิดกั้นตามนโยบาย</p>
            <p className="mt-0.5 leading-relaxed">{blockedDetail}</p>
          </div>
        </div>
      )}
      <FormError error={error} />

      <div className="flex gap-2">
        <Button type="submit" disabled={pending} className="px-3 py-1.5 text-xs">
          {pending ? "กำลังบันทึก..." : "บันทึก"}
        </Button>
        <Button
          variant="ghost"
          disabled={pending}
          className="px-3 py-1.5 text-xs"
          onClick={() => setOpen(false)}
        >
          ยกเลิก
        </Button>
      </div>
    </form>
  );
}
