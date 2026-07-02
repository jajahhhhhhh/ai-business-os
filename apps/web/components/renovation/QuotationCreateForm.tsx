"use client";

import { useState } from "react";
import type { FormEvent } from "react";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { FormError } from "@/components/ui/FormError";
import { Input, Select } from "@/components/ui/Input";
import { createContractor, createQuotation } from "@/lib/api";
import { SPEND_CATEGORY_LABELS } from "@/lib/i18n";
import { useApiAction } from "@/lib/useApiAction";

const CATEGORY_OPTIONS = Object.entries(SPEND_CATEGORY_LABELS);

/** Inline "เพิ่มใบเสนอราคา" form under the quotations table of one site. */
export function QuotationCreateForm({ siteId }: { siteId: string }) {
  const { run, pending, error, clearError } = useApiAction();
  const [open, setOpen] = useState(false);
  const [category, setCategory] = useState(CATEGORY_OPTIONS[0][0]);
  const [contractorName, setContractorName] = useState("MR.HOME");
  const [amount, setAmount] = useState("");

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const amountThb = Number(amount);
    if (!Number.isFinite(amountThb) || amountThb <= 0 || contractorName.trim() === "") {
      return;
    }

    const created = await run(async () => {
      // M1 debt (accepted): there is no GET /contractors or get-or-create
      // endpoint yet, so every submit creates a fresh contractor row — with
      // MR.HOME as the only contractor this means duplicate "MR.HOME" rows.
      // Deduplication lands with the contractor picker in a later milestone.
      const contractor = await createContractor({ name: contractorName.trim() });
      return createQuotation({
        site_id: siteId,
        contractor_id: contractor.id,
        category,
        amount_thb: amountThb,
      });
    });

    if (created) {
      setAmount("");
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
        เพิ่มใบเสนอราคา
      </Button>
    );
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="space-y-3 rounded-xl border border-slate-200 bg-slate-50/60 p-4"
    >
      <p className="text-sm font-medium text-slate-800">เพิ่มใบเสนอราคา</p>
      <div className="grid gap-3 sm:grid-cols-3">
        <label className="block text-xs font-medium text-slate-500">
          หมวดงาน
          <Select
            required
            value={category}
            onChange={(event) => setCategory(event.target.value)}
            className="mt-1 w-full"
          >
            {CATEGORY_OPTIONS.map(([slug, label]) => (
              <option key={slug} value={slug}>
                {label.th}
              </option>
            ))}
          </Select>
        </label>
        <label className="block text-xs font-medium text-slate-500">
          ผู้รับเหมา
          <Input
            required
            value={contractorName}
            onChange={(event) => setContractorName(event.target.value)}
            placeholder="MR.HOME"
            className="mt-1 w-full"
          />
        </label>
        <label className="block text-xs font-medium text-slate-500">
          จำนวนเงิน (บาท)
          <Input
            required
            type="number"
            min={1}
            step={1}
            inputMode="numeric"
            value={amount}
            onChange={(event) => setAmount(event.target.value)}
            placeholder="เช่น 150000"
            className="mt-1 w-full"
          />
        </label>
      </div>
      <FormError error={error} />
      <div className="flex gap-2">
        <Button type="submit" disabled={pending} className="px-3 py-1.5 text-xs">
          {pending ? "กำลังบันทึก..." : "บันทึกใบเสนอราคา"}
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
