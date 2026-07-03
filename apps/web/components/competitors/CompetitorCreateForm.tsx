"use client";

import { useState } from "react";
import type { FormEvent } from "react";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { FormError } from "@/components/ui/FormError";
import { Input, Select } from "@/components/ui/Input";
import { createCompetitor } from "@/lib/api";
import { COMPETITOR_KIND_LABELS } from "@/lib/i18n";
import { useApiAction } from "@/lib/useApiAction";

/** villa | hotel | aspirational | other — the API stores kind as a string. */
const KIND_OPTIONS = Object.entries(COMPETITOR_KIND_LABELS);

/** Inline "เพิ่มคู่แข่ง" form under the competitor registry table. */
export function CompetitorCreateForm() {
  const { run, pending, error, clearError } = useApiAction();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [website, setWebsite] = useState("");
  const [kind, setKind] = useState<string>("villa");

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedName = name.trim();
    if (trimmedName === "") return;
    const trimmedWebsite = website.trim();

    const created = await run(() =>
      createCompetitor({
        name: trimmedName,
        kind,
        ...(trimmedWebsite !== "" ? { website: trimmedWebsite } : {}),
      }),
    );

    if (created) {
      setName("");
      setWebsite("");
      setKind("villa");
      setOpen(false);
    }
  }

  if (!open) {
    return (
      <Button
        variant="outline"
        className="px-3 py-1.5 text-xs"
        onClick={() => {
          clearError();
          setOpen(true);
        }}
      >
        <Plus size={14} />
        เพิ่มคู่แข่ง
      </Button>
    );
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="space-y-3 rounded-xl border border-slate-200 bg-slate-50/60 p-4"
    >
      <p className="text-sm font-medium text-slate-800">เพิ่มคู่แข่ง</p>
      <div className="grid gap-3 sm:grid-cols-3">
        <label className="block text-xs font-medium text-slate-500">
          ชื่อคู่แข่ง
          <Input
            required
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="เช่น Villa Sunset Lipa Noi"
            className="mt-1 w-full"
          />
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
          ประเภท
          <Select
            required
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
      </div>
      <FormError error={error} />
      <div className="flex gap-2">
        <Button type="submit" disabled={pending} className="px-3 py-1.5 text-xs">
          {pending ? "กำลังบันทึก..." : "บันทึกคู่แข่ง"}
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
