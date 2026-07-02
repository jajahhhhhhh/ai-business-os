"use client";

/**
 * Shared mutation runner for `use client` components (M1 write flows).
 *
 * Wraps an api.ts mutation: tracks the pending state for the submit button,
 * surfaces the problem+json detail (ApiError message) for inline display, and
 * calls `router.refresh()` after the server confirms — no optimistic updates.
 */

import { useCallback, useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError } from "./api";

const NETWORK_ERROR_TH = "เชื่อมต่อเซิร์ฟเวอร์ไม่ได้ — ตรวจสอบว่า API ทำงานอยู่แล้วลองอีกครั้ง";

export interface ApiAction {
  /** Runs the mutation; resolves to the result, or null when it failed. */
  run: <T>(action: () => Promise<T>, onSuccess?: (result: T) => void) => Promise<T | null>;
  pending: boolean;
  /** Display-ready Thai error text (problem+json detail), or null. */
  error: string | null;
  clearError: () => void;
}

export function useApiAction(): ApiAction {
  const router = useRouter();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(
    async <T>(action: () => Promise<T>, onSuccess?: (result: T) => void): Promise<T | null> => {
      setPending(true);
      setError(null);
      try {
        const result = await action();
        onSuccess?.(result);
        router.refresh();
        return result;
      } catch (err) {
        setError(err instanceof ApiError ? err.message : NETWORK_ERROR_TH);
        return null;
      } finally {
        setPending(false);
      }
    },
    [router],
  );

  const clearError = useCallback(() => setError(null), []);

  return { run, pending, error, clearError };
}
