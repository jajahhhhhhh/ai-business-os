"use client";

import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { FormError } from "@/components/ui/FormError";
import { Select } from "@/components/ui/Input";
import {
  confirmBankTransaction,
  ignoreBankTransaction,
  matchBankTransaction,
} from "@/lib/api";
import type { BankTransactionStatus } from "@/lib/types";
import { useApiAction } from "@/lib/useApiAction";

/** Serializable pending-draw option built by the server page. */
export interface DrawOption {
  id: string;
  label: string;
}

/** Manual-match panel: pick a pending draw, or mark the row irrelevant. */
function MatchPanel({
  transactionId,
  pendingDraws,
  matchLabel,
  onCancel,
}: {
  transactionId: string;
  pendingDraws: DrawOption[];
  matchLabel: string;
  onCancel?: () => void;
}) {
  const { run, pending, error } = useApiAction();
  const [drawId, setDrawId] = useState("");

  return (
    <div className="space-y-2">
      {pendingDraws.length === 0 ? (
        <p className="text-xs text-slate-400">ไม่มีงวดเบิกที่รอจ่ายให้จับคู่</p>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          <Select
            value={drawId}
            onChange={(event) => setDrawId(event.target.value)}
            className="w-56 px-2 py-1.5 text-xs"
          >
            <option value="" disabled>
              เลือกงวดเบิก...
            </option>
            {pendingDraws.map((draw) => (
              <option key={draw.id} value={draw.id}>
                {draw.label}
              </option>
            ))}
          </Select>
          <Button
            disabled={pending || drawId === ""}
            className="px-3 py-1.5 text-xs"
            onClick={() => run(() => matchBankTransaction(transactionId, drawId))}
          >
            {pending ? "กำลังบันทึก..." : matchLabel}
          </Button>
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        <Button
          variant="ghost"
          disabled={pending}
          className="px-3 py-1.5 text-xs"
          onClick={() => run(() => ignoreBankTransaction(transactionId))}
        >
          ไม่เกี่ยวข้อง
        </Button>
        {onCancel && (
          <Button
            variant="ghost"
            disabled={pending}
            className="px-3 py-1.5 text-xs"
            onClick={onCancel}
          >
            ยกเลิก
          </Button>
        )}
      </div>
      <FormError error={error} />
    </div>
  );
}

/** Per-row actions for the bank-transactions table, keyed by status. */
export function TransactionActions({
  transactionId,
  status,
  ambiguousMatch,
  pendingDraws,
}: {
  transactionId: string;
  status: BankTransactionStatus;
  ambiguousMatch: boolean;
  pendingDraws: DrawOption[];
}) {
  const { run, pending, error } = useApiAction();
  const [rematching, setRematching] = useState(false);

  if (status === "confirmed" || status === "ignored") {
    return <span className="text-xs text-slate-300">—</span>;
  }

  if (status === "unmatched") {
    return (
      <MatchPanel
        transactionId={transactionId}
        pendingDraws={pendingDraws}
        matchLabel="จับคู่กับงวดเบิก"
      />
    );
  }

  // status === "matched"
  return (
    <div className="space-y-2">
      {ambiguousMatch && (
        <p className="rounded-xl bg-amber-50 px-3 py-1.5 text-xs text-amber-700">
          โปรดตรวจสอบ — มีหลายงวดที่ยอดตรงกัน
        </p>
      )}
      {rematching ? (
        <MatchPanel
          transactionId={transactionId}
          pendingDraws={pendingDraws}
          matchLabel="จับคู่"
          onCancel={() => setRematching(false)}
        />
      ) : (
        <>
          <div className="flex flex-wrap gap-2">
            <Button
              disabled={pending}
              className="px-3 py-1.5 text-xs"
              onClick={() => run(() => confirmBankTransaction(transactionId))}
            >
              {pending ? "กำลังบันทึก..." : "ยืนยัน"}
            </Button>
            <Button
              variant="outline"
              disabled={pending}
              className="px-3 py-1.5 text-xs"
              onClick={() => setRematching(true)}
            >
              ไม่ใช่รายการนี้
            </Button>
          </div>
          <FormError error={error} />
        </>
      )}
    </div>
  );
}
