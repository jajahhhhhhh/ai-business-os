"use client";

import { useState } from "react";
import type { FormEvent } from "react";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { FormError } from "@/components/ui/FormError";
import { Input } from "@/components/ui/Input";
import { createMilestone } from "@/lib/api";
import { useApiAction } from "@/lib/useApiAction";

/** Inline "เพิ่ม milestone" form under the milestone list of one site. */
export function MilestoneCreateForm({ siteId }: { siteId: string }) {
  const { run, pending, error, clearError } = useApiAction();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [plannedDate, setPlannedDate] = useState("");

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (name.trim() === "" || plannedDate === "") return;

    const ok = await run(async () => {
      await createMilestone(siteId, { name: name.trim(), planned_date: plannedDate });
      return true;
    });

    if (ok) {
      setName("");
      setPlannedDate("");
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
        เพิ่ม milestone
      </Button>
    );
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="space-y-3 rounded-xl border border-slate-200 bg-slate-50/60 p-4"
    >
      <p className="text-sm font-medium text-slate-800">เพิ่ม milestone</p>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block text-xs font-medium text-slate-500">
          ชื่องาน
          <Input
            required
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="เช่น ติดตั้งระบบไฟฟ้าชั้น 2"
            className="mt-1 w-full"
          />
        </label>
        <label className="block text-xs font-medium text-slate-500">
          กำหนดเสร็จ (ตามแผน)
          <Input
            required
            type="date"
            value={plannedDate}
            onChange={(event) => setPlannedDate(event.target.value)}
            className="mt-1 w-full"
          />
        </label>
      </div>
      <FormError error={error} />
      <div className="flex gap-2">
        <Button type="submit" disabled={pending} className="px-3 py-1.5 text-xs">
          {pending ? "กำลังบันทึก..." : "บันทึก milestone"}
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
