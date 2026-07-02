import type { Metadata } from "next";
import { BookOpen, FileText, Image as ImageIcon, Mail, Search } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardContent } from "@/components/ui/Card";
import { getHealth, safe } from "@/lib/api";

export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "คลังความรู้" };

const DOC_KINDS = [
  { icon: FileText, label: "ใบเสนอราคา / สัญญา" },
  { icon: Mail, label: "อีเมลสำคัญ" },
  { icon: ImageIcon, label: "รูปหน้างาน" },
  { icon: BookOpen, label: "โน้ตการตัดสินใจ" },
];

export default async function KnowledgeBasePage() {
  const health = await safe(getHealth());

  return (
    <div>
      <PageHeader
        title="คลังความรู้"
        subtitle="ค้นหาเอกสาร ใบเสนอราคา สัญญา และอีเมลทั้งหมด · Knowledge Base"
        action={
          health ? (
            <Badge variant="green">API พร้อมใช้งาน</Badge>
          ) : (
            <Badge variant="neutral">API ยังไม่เชื่อมต่อ</Badge>
          )
        }
      />

      {/*
        M2 seam: this search box will call GET /v1/kb/search?q=&mode=hybrid
        (Meilisearch keyword + Qdrant semantic, RRF fusion) via lib/api.ts once
        the knowledge-base service ships. Nothing is wired yet on purpose.
      */}
      <Card>
        <CardContent>
          <div className="flex flex-col gap-3 sm:flex-row">
            <div className="relative flex-1">
              <Search
                size={18}
                className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400"
              />
              <input
                type="search"
                placeholder="ค้นหาเอกสาร เช่น ใบเสนอราคางานไฟฟ้า Lipa Noi..."
                aria-label="ค้นหาคลังความรู้"
                className="h-12 w-full rounded-xl border border-slate-200 bg-slate-50 pl-11 pr-4 text-sm text-slate-700 placeholder:text-slate-400 focus:border-blue-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-blue-100"
              />
            </div>
            <Button disabled title="การค้นหาแบบไฮบริดจะเปิดใช้ใน M2">
              ค้นหา
            </Button>
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            {DOC_KINDS.map(({ icon: Icon, label }) => (
              <span
                key={label}
                className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-white px-3 py-1 text-xs text-slate-500"
              >
                <Icon size={13} />
                {label}
              </span>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Results placeholder */}
      <div className="mt-4 flex flex-col items-center rounded-2xl border border-dashed border-slate-300 bg-white px-6 py-16 text-center">
        <div className="rounded-2xl bg-blue-50 p-4 text-blue-500">
          <BookOpen size={28} />
        </div>
        <h2 className="mt-4 text-base font-semibold text-slate-900">
          การค้นหาแบบไฮบริดจะเปิดใช้ใน M2
        </h2>
        <p className="mt-1 max-w-md text-sm text-slate-500">
          เอกสารทั้งหมด — ใบเสนอราคา MR.HOME สัญญา รูปหน้างาน และอีเมล — จะถูกจัดทำดัชนีด้วย
          Meilisearch + Qdrant แล้วค้นหาได้จากช่องนี้พร้อมอ้างอิงแหล่งที่มา
        </p>
      </div>
    </div>
  );
}
