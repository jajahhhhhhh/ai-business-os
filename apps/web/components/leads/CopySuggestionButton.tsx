"use client";

import { useEffect, useRef, useState } from "react";
import { Check, Copy } from "lucide-react";
import { Button } from "@/components/ui/Button";

/** How long the "คัดลอกแล้ว" confirmation stays on the button. */
const NOTICE_MS = 2500;

/**
 * Copies the follow-up suggestion to the clipboard so the owner can paste it
 * into Reddit/LINE. Clipboard API requires a secure context — localhost is
 * fine; failures degrade to a Thai error note instead of crashing.
 */
export function CopySuggestionButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (timerRef.current !== null) clearTimeout(timerRef.current);
    };
  }, []);

  async function handleCopy() {
    if (timerRef.current !== null) clearTimeout(timerRef.current);
    setError(null);
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      timerRef.current = setTimeout(() => setCopied(false), NOTICE_MS);
    } catch {
      setError("คัดลอกไม่สำเร็จ — เลือกข้อความแล้วคัดลอกเองแทน");
    }
  }

  return (
    <div className="space-y-1.5">
      <Button
        variant="outline"
        className="px-2.5 py-1 text-xs"
        onClick={() => void handleCopy()}
      >
        {copied ? (
          <Check size={12} className="text-emerald-600" />
        ) : (
          <Copy size={12} />
        )}
        {copied ? "คัดลอกแล้ว" : "คัดลอกข้อความ"}
      </Button>
      {error && (
        <p role="alert" className="text-xs text-rose-600">
          {error}
        </p>
      )}
    </div>
  );
}
