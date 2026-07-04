"use client";

import { useEffect, useRef, useState } from "react";
import { Play } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { FormError } from "@/components/ui/FormError";
import { triggerAgentTask } from "@/lib/api";
import { AGENT_TASK_LABELS } from "@/lib/i18n";
import type { AgentTaskName } from "@/lib/types";
import { useApiAction } from "@/lib/useApiAction";

/** How long the "ส่งคำสั่งแล้ว" note stays on screen. */
const NOTICE_MS = 8000;

/** Button order — mirrors the task list of POST /v1/agents/{name}:trigger. */
const TASKS: AgentTaskName[] = [
  "analytics-daily",
  "analytics-weekly",
  "planner",
  "memory-consolidate",
  "memory-capture",
  "qa-evaluate",
];

/**
 * Manual trigger buttons — POST /v1/agents/{name}:trigger (202). Shows a
 * transient accepted note; the run itself lands in the runs table once the
 * orchestrator picks it up, so the owner refreshes to follow progress.
 */
export function AgentTriggerCard() {
  const { run, pending, error } = useApiAction();
  const [activeTask, setActiveTask] = useState<AgentTaskName | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (timerRef.current !== null) clearTimeout(timerRef.current);
    };
  }, []);

  const trigger = async (task: AgentTaskName) => {
    if (timerRef.current !== null) clearTimeout(timerRef.current);
    setNotice(null);
    setActiveTask(task);
    const result = await run(() => triggerAgentTask(task));
    setActiveTask(null);
    if (result) {
      setNotice("ส่งคำสั่งแล้ว — ดูผลในตาราง run");
      timerRef.current = setTimeout(() => setNotice(null), NOTICE_MS);
    }
  };

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {TASKS.map((task) => {
          const isActive = pending && activeTask === task;
          return (
            <Button
              key={task}
              variant="outline"
              disabled={pending}
              className="justify-start px-3 py-2 text-xs"
              onClick={() => void trigger(task)}
            >
              <Play size={13} className={isActive ? "animate-pulse" : undefined} />
              {isActive ? "กำลังส่งคำสั่ง..." : AGENT_TASK_LABELS[task].th}
            </Button>
          );
        })}
      </div>
      {notice && (
        <p role="status" className="rounded-xl bg-blue-50 px-3 py-1.5 text-xs text-blue-700">
          {notice}
        </p>
      )}
      <FormError error={error} />
    </div>
  );
}
