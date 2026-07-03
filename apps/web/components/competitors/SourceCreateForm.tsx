"use client";

import { useState } from "react";
import type { FormEvent } from "react";
import { useRouter } from "next/navigation";
import { Plus, TriangleAlert } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { FormError } from "@/components/ui/FormError";
import { Input, Select } from "@/components/ui/Input";
import { ApiError, createSource } from "@/lib/api";
import { SOURCE_TYPE_LABELS } from "@/lib/i18n";
import type { SourceType } from "@/lib/types";

const TYPE_OPTIONS: SourceType[] = ["website", "rss", "sitemap"];

const NETWORK_ERROR_TH =
  "เชื่อมต่อเซิร์ฟเวอร์ไม่ได้ — ตรวจสอบว่า API ทำงานอยู่แล้วลองอีกครั้ง";

/** Serializable competitor option built by the server page. */
export interface CompetitorOption {
  id: string;
  name: string;
}

/**
 * Inline "เพิ่มแหล่งข้อมูล" form. Does not use useApiAction because a 422
 * needs special treatment: it is the ToS compliance gate rejecting the URL
 * (e.g. facebook.com, airbnb) — shown as an amber policy note, not a generic
 * error.
 */
export function SourceCreateForm({ competitors }: { competitors: CompetitorOption[] }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  /** problem+json detail from the 422 ToS compliance gate. */
  const [tosDetail, setTosDetail] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [competitorId, setCompetitorId] = useState("");
  const [type, setType] = useState<SourceType>("website");
  const [url, setUrl] = useState("");

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedName = name.trim();
    const trimmedUrl = url.trim();
    if (trimmedName === "" || trimmedUrl === "") return;

    setPending(true);
    setError(null);
    setTosDetail(null);
    try {
      await createSource({
        name: trimmedName,
        type,
        url: trimmedUrl,
        ...(competitorId !== "" ? { competitor_id: competitorId } : {}),
      });
      router.refresh();
      setName("");
      setUrl("");
      setCompetitorId("");
      setType("website");
      setOpen(false);
    } catch (err) {
      if (err instanceof ApiError && err.status === 422) {
        setTosDetail(err.message);
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
        variant="outline"
        className="px-3 py-1.5 text-xs"
        onClick={() => {
          setError(null);
          setTosDetail(null);
          setOpen(true);
        }}
      >
        <Plus size={14} />
        เพิ่มแหล่งข้อมูล
      </Button>
    );
  }

  function handleTypeChange(value: string) {
    // The select only offers TYPE_OPTIONS values — validate instead of casting.
    const match = TYPE_OPTIONS.find((option) => option === value);
    if (match) setType(match);
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="space-y-3 rounded-xl border border-slate-200 bg-slate-50/60 p-4"
    >
      <p className="text-sm font-medium text-slate-800">เพิ่มแหล่งข้อมูล</p>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <label className="block text-xs font-medium text-slate-500">
          ชื่อแหล่งข้อมูล
          <Input
            required
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="เช่น เว็บไซต์หลัก Villa Sunset"
            className="mt-1 w-full"
          />
        </label>
        <label className="block text-xs font-medium text-slate-500">
          คู่แข่ง
          <Select
            value={competitorId}
            onChange={(event) => setCompetitorId(event.target.value)}
            className="mt-1 w-full"
          >
            <option value="">ไม่ระบุ (แหล่งข้อมูลรวม)</option>
            {competitors.map((competitor) => (
              <option key={competitor.id} value={competitor.id}>
                {competitor.name}
              </option>
            ))}
          </Select>
        </label>
        <label className="block text-xs font-medium text-slate-500">
          ประเภท
          <Select
            required
            value={type}
            onChange={(event) => handleTypeChange(event.target.value)}
            className="mt-1 w-full"
          >
            {TYPE_OPTIONS.map((option) => (
              <option key={option} value={option}>
                {SOURCE_TYPE_LABELS[option].th}
              </option>
            ))}
          </Select>
        </label>
        <label className="block text-xs font-medium text-slate-500">
          URL
          <Input
            required
            type="url"
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            placeholder="https://..."
            className="mt-1 w-full"
          />
        </label>
      </div>

      {tosDetail && (
        <p
          role="alert"
          className="flex items-start gap-2 rounded-xl bg-amber-50 px-3 py-2 text-xs text-amber-800"
        >
          <TriangleAlert size={14} className="mt-0.5 shrink-0" />
          <span>
            <span className="font-semibold">แหล่งข้อมูลนี้ไม่ผ่านนโยบาย ToS</span>
            {" — "}
            {tosDetail}
          </span>
        </p>
      )}
      <FormError error={error} />

      <div className="flex gap-2">
        <Button type="submit" disabled={pending} className="px-3 py-1.5 text-xs">
          {pending ? "กำลังบันทึก..." : "บันทึกแหล่งข้อมูล"}
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
