"use client";

import { useState } from "react";
import type { FormEvent } from "react";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { FormError } from "@/components/ui/FormError";
import { Input, Select } from "@/components/ui/Input";
import { createDraw } from "@/lib/api";
import { useApiAction } from "@/lib/useApiAction";

/** Serializable quotation option built by the server page. */
export interface QuotationOption {
  id: string;
  label: string;
}

/** Inline "เพิ่มงวดเบิก" form under the draw pipeline of one site. */
export function DrawCreateForm({ quotations }: { quotations: QuotationOption[] }) {
  const { run, pending, error, clearError } = useApiAction();
  const [open, setOpen] = useState(false);
  const [quotationId, setQuotationId] = useState("");
  const [amount, setAmount] = useState("");

  if (quotations.length === 0) {
    return (
      <p className="text-xs text-slate-400">
        ต้องมีใบเสนอราคาก่อน จึงจะเพิ่มงวดเบิกได้ — เพิ่มใบเสนอราคาด้านบน
      </p>
    );
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const amountThb = Number(amount);
    if (quotationId === "" || !Number.isFinite(amountThb) || amountThb <= 0) {
      return;
    }

    const ok = await run(async () => {
      await createDraw({ quotation_id: quotationId, amount_thb: amountThb });
      return true;
    });

    if (ok) {
      setAmount("");
      setQuotationId("");
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
        เพิ่มงวดเบิก
      </Button>
    );
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="space-y-3 rounded-xl border border-slate-200 bg-slate-50/60 p-4"
    >
      <p className="text-sm font-medium text-slate-800">เพิ่มงวดเบิก</p>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block text-xs font-medium text-slate-500">
          ใบเสนอราคา
          <Select
            required
            value={quotationId}
            onChange={(event) => setQuotationId(event.target.value)}
            className="mt-1 w-full"
          >
            <option value="" disabled>
              เลือกใบเสนอราคา...
            </option>
            {quotations.map((quotation) => (
              <option key={quotation.id} value={quotation.id}>
                {quotation.label}
              </option>
            ))}
          </Select>
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
            placeholder="เช่น 50000"
            className="mt-1 w-full"
          />
        </label>
      </div>
      <FormError error={error} />
      <div className="flex gap-2">
        <Button type="submit" disabled={pending} className="px-3 py-1.5 text-xs">
          {pending ? "กำลังบันทึก..." : "บันทึกงวดเบิก"}
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
