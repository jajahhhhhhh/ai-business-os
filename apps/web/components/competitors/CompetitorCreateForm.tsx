"use client";

import { useState } from "react";
import type { FormEvent } from "react";
import { useRouter } from "next/navigation";
import { ShieldAlert } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { FormError } from "@/components/ui/FormError";
import { Input, Select } from "@/components/ui/Input";
import { ApiError, createCompetitor } from "@/lib/api";
import { COMPETITOR_KIND_LABELS } from "@/lib/i18n";
import type { CompetitorSourceCreate } from "@/lib/types";

/** villa | hotel | aspirational | other — the API stores kind as a string. */
const KIND_OPTIONS = Object.entries(COMPETITOR_KIND_LABELS);

const NETWORK_ERROR_TH =
  "เชื่อมต่อเซิร์ฟเวอร์ไม่ได้ — ตรวจสอบว่า API ทำงานอยู่แล้วลองอีกครั้ง";

/**
 * "เพิ่มคู่แข่ง" card body. The website URL becomes both the competitor's
 * website and a `website` source; the RSS URL becomes an `rss` source.
 *
 * Does not use useApiAction because a 422 needs special treatment: it is the
 * ToS compliance gate refusing a blocked domain (Facebook / Airbnb / Booking /
 * Agoda) — its Thai detail is shown as a prominent policy panel, not a
 * generic error.
 */
export function CompetitorCreateForm() {
  const router = useRouter();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  /** problem+json detail from the 422 ToS compliance gate. */
  const [blockedDetail, setBlockedDetail] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [kind, setKind] = useState<string>("villa");
  const [website, setWebsite] = useState("");
  const [rssUrl, setRssUrl] = useState("");

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedName = name.trim();
    if (trimmedName === "") return;
    const trimmedWebsite = website.trim();
    const trimmedRss = rssUrl.trim();

    const sources: CompetitorSourceCreate[] = [];
    if (trimmedWebsite !== "") sources.push({ type: "website", url: trimmedWebsite });
    if (trimmedRss !== "") sources.push({ type: "rss", url: trimmedRss });

    setPending(true);
    setError(null);
    setBlockedDetail(null);
    try {
      await createCompetitor({
        name: trimmedName,
        kind,
        ...(trimmedWebsite !== "" ? { website: trimmedWebsite } : {}),
        ...(sources.length > 0 ? { sources } : {}),
      });
      router.refresh();
      setName("");
      setKind("villa");
      setWebsite("");
      setRssUrl("");
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

  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <label className="block text-xs font-medium text-slate-500">
          ชื่อคู่แข่ง <span className="text-rose-500">*</span>
          <Input
            required
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="เช่น Villa Sunset Lipa Noi"
            className="mt-1 w-full"
          />
        </label>
        <label className="block text-xs font-medium text-slate-500">
          ประเภท
          <Select
            value={kind}
            onChange={(event) => setKind(event.target.value)}
            className="mt-1 w-full"
          >
            {KIND_OPTIONS.map(([slug, label]) => (
              <option key={slug} value={slug}>
                {label.th}
              </option>
            ))}
          </Select>
        </label>
        <label className="block text-xs font-medium text-slate-500">
          เว็บไซต์ (ถ้ามี)
          <Input
            type="url"
            value={website}
            onChange={(event) => setWebsite(event.target.value)}
            placeholder="https://..."
            className="mt-1 w-full"
          />
        </label>
        <label className="block text-xs font-medium text-slate-500">
          ฟีด RSS (ถ้ามี)
          <Input
            type="url"
            value={rssUrl}
            onChange={(event) => setRssUrl(event.target.value)}
            placeholder="https://.../feed.xml"
            className="mt-1 w-full"
          />
        </label>
      </div>

      {blockedDetail && (
        <div
          role="alert"
          className="flex items-start gap-3 rounded-xl border border-amber-300 bg-amber-50 px-4 py-3"
        >
          <ShieldAlert size={18} className="mt-0.5 shrink-0 text-amber-600" />
          <div className="text-sm text-amber-900">
            <p className="font-semibold">แหล่งข้อมูลนี้ถูกปิดกั้นตามนโยบาย</p>
            <p className="mt-1 leading-relaxed">{blockedDetail}</p>
            <p className="mt-1 text-xs text-amber-700">
              ใช้เว็บไซต์ทางการหรือฟีด RSS ของคู่แข่งแทน
            </p>
          </div>
        </div>
      )}
      <FormError error={error} />

      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" disabled={pending} className="px-3 py-1.5 text-xs">
          {pending ? "กำลังบันทึก..." : "เพิ่มคู่แข่ง"}
        </Button>
        <p className="text-xs text-slate-400">
          Facebook / Airbnb / Booking / Agoda ถูกปิดกั้นตามนโยบายแหล่งข้อมูล
        </p>
      </div>
    </form>
  );
}
