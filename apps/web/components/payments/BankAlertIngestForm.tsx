"use client";

import { useState } from "react";
import type { FormEvent } from "react";
import { CheckCircle2 } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { FormError } from "@/components/ui/FormError";
import { Textarea } from "@/components/ui/Input";
import { ingestBankAlert } from "@/lib/api";
import { formatDateTimeTH, formatTHB } from "@/lib/format";
import { BANK_TX_DIRECTION_LABELS, BANK_TX_STATUS_LABELS } from "@/lib/i18n";
import type { BankTransaction } from "@/lib/types";
import { useApiAction } from "@/lib/useApiAction";

/** Paste-ingest form: bank alert text (email/SMS) → parsed BankTransaction. */
export function BankAlertIngestForm() {
  const { run, pending, error } = useApiAction();
  const [rawText, setRawText] = useState("");
  const [result, setResult] = useState<BankTransaction | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (rawText.trim() === "") return;

    setResult(null);
    const transaction = await run(() => ingestBankAlert(rawText.trim()));
    if (transaction) {
      setResult(transaction);
      setRawText("");
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      <Textarea
        required
        rows={4}
        value={rawText}
        onChange={(event) => setRawText(event.target.value)}
        placeholder="วางข้อความแจ้งเตือนจากธนาคาร (อีเมล/SMS)..."
        className="w-full"
      />
      <FormError error={error} />

      {result && (
        <div className="flex flex-wrap items-center gap-2 rounded-xl bg-emerald-50 px-3 py-2.5 text-sm text-emerald-800">
          <CheckCircle2 size={16} className="shrink-0" />
          <span>
            อ่านรายการสำเร็จ — {result.bank} · เงิน
            {BANK_TX_DIRECTION_LABELS[result.direction].th} {formatTHB(result.amount_thb)} ·{" "}
            {formatDateTimeTH(result.occurred_at)}
            {result.account_tail ? ` · บัญชี ...${result.account_tail}` : ""}
          </span>
          <Badge variant={result.status === "matched" ? "blue" : "neutral"}>
            {BANK_TX_STATUS_LABELS[result.status].th}
          </Badge>
          {result.ambiguous_match && (
            <span className="text-xs text-amber-700">
              โปรดตรวจสอบ — มีหลายงวดที่ยอดตรงกัน
            </span>
          )}
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3">
        <Button type="submit" disabled={pending}>
          {pending ? "กำลังบันทึก..." : "บันทึกรายการ"}
        </Button>
        <p className="text-xs text-slate-400">
          เชื่อมต่อ Gmail เพื่อดึงอัตโนมัติ — ตั้งค่า GMAIL_* ใน .env (ดู docs)
        </p>
      </div>
    </form>
  );
}
