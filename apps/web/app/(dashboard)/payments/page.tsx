import type { Metadata } from "next";
import { ArrowDownLeft, ArrowUpRight } from "lucide-react";
import { DataTable } from "@/components/DataTable";
import type { Column } from "@/components/DataTable";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { BankAlertIngestForm } from "@/components/payments/BankAlertIngestForm";
import { DailySnapshotButton } from "@/components/payments/DailySnapshotButton";
import { TransactionActions } from "@/components/payments/TransactionActions";
import type { DrawOption } from "@/components/payments/TransactionActions";
import { Badge } from "@/components/ui/Badge";
import type { BadgeVariant } from "@/components/ui/Badge";
import { Card, CardContent, CardHeader } from "@/components/ui/Card";
import { listBankTransactions, listDraws, safe } from "@/lib/api";
import { formatDateTimeTH, formatTHB } from "@/lib/format";
import { BANK_TX_DIRECTION_LABELS, BANK_TX_STATUS_LABELS, categoryLabel } from "@/lib/i18n";
import type { BankTransaction, BankTransactionStatus, DrawRow } from "@/lib/types";

export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "การเงิน" };

const TX_STATUS_BADGE: Record<BankTransactionStatus, BadgeVariant> = {
  unmatched: "amber",
  matched: "blue",
  confirmed: "green",
  ignored: "neutral",
};

function drawLabel(draw: DrawRow): string {
  return `งวด #${draw.seq} · ${categoryLabel(draw.category)} · ${draw.site_name} · ${formatTHB(draw.amount_thb)}`;
}

function buildColumns(
  pendingDraws: DrawOption[],
  drawsById: Map<string, DrawRow>,
): Column<BankTransaction>[] {
  return [
    {
      key: "occurred_at",
      header: "วันเวลา",
      render: (tx) => (
        <span className="whitespace-nowrap">{formatDateTimeTH(tx.occurred_at)}</span>
      ),
    },
    {
      key: "bank",
      header: "ธนาคาร",
      render: (tx) => tx.bank,
    },
    {
      key: "direction",
      header: "เข้า/ออก",
      render: (tx) =>
        tx.direction === "in" ? (
          <Badge variant="green">
            <ArrowDownLeft size={12} />
            {BANK_TX_DIRECTION_LABELS.in.th}
          </Badge>
        ) : (
          <Badge variant="red">
            <ArrowUpRight size={12} />
            {BANK_TX_DIRECTION_LABELS.out.th}
          </Badge>
        ),
    },
    {
      key: "amount",
      header: "จำนวนเงิน",
      align: "right",
      render: (tx) => (
        <span className="font-medium text-slate-900">{formatTHB(tx.amount_thb)}</span>
      ),
    },
    {
      key: "account",
      header: "บัญชี",
      render: (tx) => (tx.account_tail ? `...${tx.account_tail}` : "—"),
    },
    {
      key: "status",
      header: "สถานะ",
      render: (tx) => (
        <Badge variant={TX_STATUS_BADGE[tx.status]}>{BANK_TX_STATUS_LABELS[tx.status].th}</Badge>
      ),
    },
    {
      key: "matched_draw",
      header: "งวดที่จับคู่",
      render: (tx) => {
        if (!tx.matched_draw_id) return <span className="text-slate-300">—</span>;
        const draw = drawsById.get(tx.matched_draw_id);
        if (!draw) return <span className="text-xs text-slate-400">งวดเบิก (ไม่พบรายละเอียด)</span>;
        return (
          <div className="text-xs">
            <p className="font-medium text-slate-800">
              งวด #{draw.seq} · {categoryLabel(draw.category)}
            </p>
            <p className="text-slate-400">
              {draw.site_name} · {draw.contractor_name} · {formatTHB(draw.amount_thb)}
            </p>
          </div>
        );
      },
    },
    {
      key: "actions",
      header: "จัดการ",
      render: (tx) => (
        <TransactionActions
          transactionId={tx.id}
          status={tx.status}
          ambiguousMatch={tx.ambiguous_match}
          pendingDraws={pendingDraws}
        />
      ),
    },
  ];
}

export default async function PaymentsPage() {
  const [transactions, draws] = await Promise.all([
    safe(listBankTransactions({ limit: 100 })),
    safe(listDraws()),
  ]);

  const drawsById = new Map((draws ?? []).map((draw) => [draw.id, draw]));
  const pendingDraws: DrawOption[] = (draws ?? [])
    .filter((draw) => draw.status === "pending")
    .map((draw) => ({ id: draw.id, label: drawLabel(draw) }));

  const rows = (transactions ?? [])
    .slice()
    .sort((a, b) => b.occurred_at.localeCompare(a.occurred_at));

  return (
    <div>
      <PageHeader
        title="การเงิน"
        subtitle="รายการธนาคารและการจับคู่งวดเบิก · Payments"
        action={<DailySnapshotButton />}
      />

      <div className="space-y-6">
        <Card>
          <CardHeader
            title="บันทึกแจ้งเตือนธนาคาร"
            subtitle="วางข้อความจากอีเมล/SMS ระบบจะอ่านยอดและจับคู่งวดเบิกให้อัตโนมัติ"
          />
          <CardContent>
            <BankAlertIngestForm />
          </CardContent>
        </Card>

        {transactions === null ? (
          <EmptyState />
        ) : (
          <Card>
            <CardHeader
              title="รายการธนาคาร"
              subtitle="เรียงจากรายการล่าสุด"
              action={<Badge variant="blue">{rows.length} รายการ</Badge>}
            />
            <CardContent>
              <DataTable
                columns={buildColumns(pendingDraws, drawsById)}
                rows={rows}
                rowKey={(tx) => tx.id}
                emptyText="ยังไม่มีรายการธนาคาร — วางข้อความแจ้งเตือนด้านบนเพื่อเริ่มบันทึก"
              />
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
