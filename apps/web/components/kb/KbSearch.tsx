"use client";

import { useState } from "react";
import type { FormEvent } from "react";
import { FileText, Loader2, Search, SearchX, TriangleAlert } from "lucide-react";
import { EmptyState } from "@/components/EmptyState";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardContent } from "@/components/ui/Card";
import { ApiError, searchKb } from "@/lib/api";
import { KB_SEARCH_MODE_LABELS, kbMatchedByLabel } from "@/lib/i18n";
import type { KbSearchMode, KbSearchResponse, KbSearchResult } from "@/lib/types";

const MODES: KbSearchMode[] = ["hybrid", "keyword", "semantic"];
const RESULT_LIMIT = 20;
const NETWORK_ERROR_TH =
  "เชื่อมต่อเซิร์ฟเวอร์ไม่ได้ — ตรวจสอบว่า API ทำงานอยู่แล้วลองอีกครั้ง";

/**
 * Relevance bar width, normalized against the best score in this result set —
 * RRF fusion scores are tiny absolute numbers, so raw values would render as
 * invisible slivers.
 */
function relevancePercent(score: number, maxScore: number): number {
  if (maxScore <= 0 || score <= 0) return 4;
  return Math.max(4, Math.min(100, Math.round((score / maxScore) * 100)));
}

function ResultCard({ result, maxScore }: { result: KbSearchResult; maxScore: number }) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <FileText size={15} className="shrink-0 text-slate-400" />
          <span className="text-sm font-semibold text-slate-900">
            {result.document_title}
          </span>
          <span className="text-xs text-slate-400">ตอนที่ {result.seq + 1}</span>
          <span className="ml-auto flex items-center gap-1">
            {result.matched_by.map((matcher) => (
              <Badge key={matcher} variant={matcher === "keyword" ? "blue" : "neutral"}>
                {kbMatchedByLabel(matcher)}
              </Badge>
            ))}
          </span>
        </div>

        {/* CSS truncation keeps long Thai chunks readable without measuring glyphs. */}
        <p className="mt-2 line-clamp-4 whitespace-pre-line text-sm leading-relaxed text-slate-600">
          {result.text}
        </p>

        <div
          className="mt-3 h-1 w-full overflow-hidden rounded-full bg-slate-100"
          title={`คะแนนความเกี่ยวข้อง ${result.score.toFixed(4)}`}
          aria-hidden
        >
          <div
            className="h-full rounded-full bg-blue-300"
            style={{ width: `${relevancePercent(result.score, maxScore)}%` }}
          />
        </div>
      </CardContent>
    </Card>
  );
}

/** Client-side hybrid search: input + mode chips → GET /v1/kb/search. */
export function KbSearch() {
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<KbSearchMode>("hybrid");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [response, setResponse] = useState<KbSearchResponse | null>(null);

  async function runSearch(nextMode: KbSearchMode) {
    const q = query.trim();
    if (q === "") return; // empty query — never call the API

    setLoading(true);
    setError(null);
    try {
      setResponse(await searchKb({ q, mode: nextMode, limit: RESULT_LIMIT }));
    } catch (err) {
      setError(
        err instanceof ApiError
          ? `ค้นหาไม่สำเร็จ (HTTP ${err.status}) — ลองอีกครั้ง`
          : NETWORK_ERROR_TH,
      );
    } finally {
      setLoading(false);
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void runSearch(mode);
  }

  function handleModeChange(nextMode: KbSearchMode) {
    setMode(nextMode);
    // Already showing results — re-run so the toggle feels live.
    if (response !== null && query.trim() !== "") void runSearch(nextMode);
  }

  const maxScore =
    response?.results.reduce((max, result) => Math.max(max, result.score), 0) ?? 0;

  return (
    <section aria-label="ค้นหาคลังความรู้">
      <Card>
        <CardContent>
          <form onSubmit={handleSubmit} className="flex flex-col gap-3 sm:flex-row">
            <div className="relative flex-1">
              <Search
                size={18}
                className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400"
              />
              <input
                type="search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="ค้นหาใบเสนอราคา สัญญา เอกสาร..."
                aria-label="ค้นหาคลังความรู้"
                className="h-12 w-full rounded-xl border border-slate-200 bg-slate-50 pl-11 pr-4 text-sm text-slate-700 placeholder:text-slate-400 focus:border-blue-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-blue-100"
              />
            </div>
            <Button type="submit" disabled={loading || query.trim() === ""}>
              {loading ? (
                <>
                  <Loader2 size={16} className="animate-spin" />
                  กำลังค้นหา...
                </>
              ) : (
                "ค้นหา"
              )}
            </Button>
          </form>

          <div className="mt-4 flex flex-wrap items-center gap-2" role="group" aria-label="โหมดการค้นหา">
            {MODES.map((candidate) => {
              const active = candidate === mode;
              return (
                <button
                  key={candidate}
                  type="button"
                  onClick={() => handleModeChange(candidate)}
                  aria-pressed={active}
                  className={`rounded-full border px-3 py-1 text-xs font-medium transition-colors ${
                    active
                      ? "border-blue-200 bg-blue-50 text-blue-700"
                      : "border-slate-200 bg-white text-slate-500 hover:bg-slate-50"
                  }`}
                >
                  {KB_SEARCH_MODE_LABELS[candidate].th}
                </button>
              );
            })}
            <span className="text-xs text-slate-400">
              ไฮบริด = คีย์เวิร์ด + ความหมาย (แนะนำ)
            </span>
          </div>
        </CardContent>
      </Card>

      {error && (
        <p role="alert" className="mt-3 rounded-xl bg-rose-50 px-3 py-2 text-xs text-rose-700">
          {error}
        </p>
      )}

      {response && !loading && !error && (
        <div className="mt-4">
          {response.degraded && (
            <p className="mb-3 flex items-center gap-2 rounded-xl bg-amber-50 px-3 py-2 text-xs text-amber-700">
              <TriangleAlert size={14} className="shrink-0" />
              โหมดความหมายยังไม่พร้อม — แสดงผลจากคีย์เวิร์ดเท่านั้น
            </p>
          )}

          {response.results.length === 0 ? (
            <EmptyState
              icon={SearchX}
              title="ไม่พบเอกสารที่ตรงกับคำค้น"
              description={`ไม่มีผลลัพธ์สำหรับ "${response.query}" — ลองเปลี่ยนคำค้นหรือสลับโหมดการค้นหา`}
            />
          ) : (
            <div className="space-y-3">
              <p className="text-xs text-slate-400">
                พบ {response.results.length} รายการสำหรับ &ldquo;{response.query}&rdquo;
              </p>
              {response.results.map((result) => (
                <ResultCard key={result.chunk_id} result={result} maxScore={maxScore} />
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
