"use client";

import { useState } from "react";
import type { FormEvent } from "react";
import { useRouter } from "next/navigation";
import { ShieldAlert } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { FormError } from "@/components/ui/FormError";
import { Input, Select } from "@/components/ui/Input";
import { ApiError, createSource } from "@/lib/api";
import { LEAD_SOURCE_TYPE_LABELS } from "@/lib/i18n";
import type { LeadSourceCreate, LeadSourceType } from "@/lib/types";

const TYPE_OPTIONS: LeadSourceType[] = ["reddit", "rss"];

const NETWORK_ERROR_TH =
  "เชื่อมต่อเซิร์ฟเวอร์ไม่ได้ — ตรวจสอบว่า API ทำงานอยู่แล้วลองอีกครั้ง";

/**
 * "เพิ่มแหล่งค้นหาลูกค้า" card body — POST /v1/sources.
 *
 * Reddit sources take a subreddit (+ optional search query) and always go
 * through the official API; RSS sources take a feed URL.
 *
 * Does not use useApiAction because a 422 needs special treatment: it is the
 * ToS compliance gate (§8.4) refusing a blocked domain — its Thai detail is
 * shown as a prominent policy panel, not a generic error.
 */
export function LeadSourceCreateForm() {
  const router = useRouter();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  /** problem+json detail from the 422 ToS compliance gate. */
  const [blockedDetail, setBlockedDetail] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [type, setType] = useState<LeadSourceType>("reddit");
  const [subreddit, setSubreddit] = useState("");
  const [query, setQuery] = useState("");
  const [url, setUrl] = useState("");

  function handleTypeChange(value: string) {
    // The select only offers TYPE_OPTIONS values — validate instead of casting.
    const match = TYPE_OPTIONS.find((option) => option === value);
    if (match) setType(match);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedName = name.trim();
    if (trimmedName === "") return;

    let payload: LeadSourceCreate;
    if (type === "reddit") {
      // Accept "r/kohsamui", "/r/kohsamui" or a bare "kohsamui".
      const cleanSubreddit = subreddit.trim().replace(/^\/?r\//i, "");
      if (cleanSubreddit === "") return;
      const trimmedQuery = query.trim();
      payload = {
        name: trimmedName,
        type,
        config: {
          subreddit: cleanSubreddit,
          ...(trimmedQuery !== "" ? { query: trimmedQuery } : {}),
        },
      };
    } else {
      const trimmedUrl = url.trim();
      if (trimmedUrl === "") return;
      payload = { name: trimmedName, type, url: trimmedUrl };
    }

    setPending(true);
    setError(null);
    setBlockedDetail(null);
    try {
      await createSource(payload);
      router.refresh();
      setName("");
      setSubreddit("");
      setQuery("");
      setUrl("");
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
          ชื่อแหล่งข้อมูล <span className="text-rose-500">*</span>
          <Input
            required
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="เช่น Reddit r/kohsamui"
            className="mt-1 w-full"
          />
        </label>
        <label className="block text-xs font-medium text-slate-500">
          ประเภท
          <Select
            value={type}
            onChange={(event) => handleTypeChange(event.target.value)}
            className="mt-1 w-full"
          >
            {TYPE_OPTIONS.map((option) => (
              <option key={option} value={option}>
                {LEAD_SOURCE_TYPE_LABELS[option].th}
              </option>
            ))}
          </Select>
        </label>

        {type === "reddit" ? (
          <>
            <label className="block text-xs font-medium text-slate-500">
              Subreddit <span className="text-rose-500">*</span>
              <Input
                required
                value={subreddit}
                onChange={(event) => setSubreddit(event.target.value)}
                placeholder="เช่น kohsamui หรือ digitalnomad"
                className="mt-1 w-full"
              />
            </label>
            <label className="block text-xs font-medium text-slate-500">
              คำค้นหา (ถ้ามี)
              <Input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="เช่น villa OR long stay"
                className="mt-1 w-full"
              />
            </label>
          </>
        ) : (
          <label className="block text-xs font-medium text-slate-500 sm:col-span-2">
            URL ฟีด RSS <span className="text-rose-500">*</span>
            <Input
              required
              type="url"
              value={url}
              onChange={(event) => setUrl(event.target.value)}
              placeholder="https://.../feed.xml"
              className="mt-1 w-full"
            />
          </label>
        )}
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
              ใช้ subreddit สาธารณะหรือฟีด RSS ทางการแทน
            </p>
          </div>
        </div>
      )}
      <FormError error={error} />

      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" disabled={pending} className="px-3 py-1.5 text-xs">
          {pending ? "กำลังบันทึก..." : "เพิ่มแหล่งข้อมูล"}
        </Button>
        <p className="text-xs text-slate-400">
          เฉพาะแหล่งข้อมูลสาธารณะตามนโยบาย §8.4 — Reddit ผ่าน API ทางการเท่านั้น
        </p>
      </div>
    </form>
  );
}
