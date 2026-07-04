"use client";

import { ArrowRight, Check, X } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { FormError } from "@/components/ui/FormError";
import { moveLead } from "@/lib/api";
import { LEAD_STAGE_LABELS } from "@/lib/i18n";
import type { LeadStage } from "@/lib/types";
import { useApiAction } from "@/lib/useApiAction";

/**
 * Allowed pipeline transitions (ARCHITECTURE §M5):
 * discovered → qualified → contacted → won | lost. Terminal stages render
 * nothing.
 */
const NEXT_STAGES: Record<LeadStage, LeadStage[]> = {
  discovered: ["qualified"],
  qualified: ["contacted"],
  contacted: ["won", "lost"],
  won: [],
  lost: [],
};

function stageIcon(target: LeadStage) {
  if (target === "won") return <Check size={12} className="shrink-0" />;
  if (target === "lost") return <X size={12} className="shrink-0" />;
  return <ArrowRight size={12} className="shrink-0" />;
}

/**
 * Advance buttons on a pipeline card / the detail header —
 * POST /v1/leads/{id}/stage. An invalid transition gets a 409 problem+json
 * (Thai detail) which is rendered inline; success refreshes the server page.
 */
export function LeadAdvanceButtons({
  leadId,
  stage,
}: {
  leadId: string;
  stage: LeadStage;
}) {
  const { run, pending, error } = useApiAction();
  const targets = NEXT_STAGES[stage];

  if (targets.length === 0) return null;

  return (
    <div className="space-y-1.5">
      <div className="flex flex-wrap gap-1.5">
        {targets.map((target) => (
          <Button
            key={target}
            variant={target === "lost" ? "ghost" : "outline"}
            disabled={pending}
            className="px-2.5 py-1 text-xs"
            onClick={() => void run(() => moveLead(leadId, target))}
          >
            {stageIcon(target)}
            {pending ? "กำลังบันทึก..." : LEAD_STAGE_LABELS[target].th}
          </Button>
        ))}
      </div>
      <FormError error={error} />
    </div>
  );
}
