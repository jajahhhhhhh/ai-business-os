"use client";

import { useState } from "react";
import { Radar } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { FormError } from "@/components/ui/FormError";
import { sweepCompetitor } from "@/lib/api";
import { useApiAction } from "@/lib/useApiAction";

/**
 * Per-competitor "สแกนตอนนี้" — POST /v1/competitors/{id}:sweep (202).
 * The accepted detail is shown inline; results appear in the change feed
 * once the collector finishes.
 */
export function SweepButton({ competitorId }: { competitorId: string }) {
  const { run, pending, error } = useApiAction();
  const [detail, setDetail] = useState<string | null>(null);

  return (
    <div className="space-y-1.5">
      <Button
        variant="outline"
        disabled={pending}
        className="px-3 py-1.5 text-xs"
        onClick={async () => {
          setDetail(null);
          const result = await run(() => sweepCompetitor(competitorId));
          if (result) setDetail(result.detail);
        }}
      >
        <Radar size={13} className={pending ? "animate-pulse" : undefined} />
        {pending ? "กำลังส่งคำสั่ง..." : "สแกนตอนนี้"}
      </Button>
      {detail && (
        <p className="max-w-[14rem] rounded-xl bg-blue-50 px-3 py-1.5 text-xs text-blue-700">
          {detail}
        </p>
      )}
      <FormError error={error} />
    </div>
  );
}
