"use client";

import { useTransition } from "react";
import { useRouter } from "next/navigation";
import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/Button";

/**
 * Re-fetches the server-rendered document list — ingestion is async (202),
 * so pending/parsing rows update on refresh rather than polling.
 */
export function KbRefreshButton() {
  const router = useRouter();
  const [pending, startTransition] = useTransition();

  return (
    <Button
      variant="outline"
      disabled={pending}
      onClick={() => startTransition(() => router.refresh())}
      className="px-3 py-1.5 text-xs"
    >
      <RefreshCw size={13} className={pending ? "animate-spin" : undefined} />
      รีเฟรช
    </Button>
  );
}
