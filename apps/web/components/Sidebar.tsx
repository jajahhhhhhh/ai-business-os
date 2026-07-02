"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  BookOpen,
  Bot,
  FileText,
  Hammer,
  LayoutDashboard,
  Radar,
  Settings,
  Users,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { t } from "@/lib/i18n";

interface NavItem {
  href: string;
  th: string;
  en: string;
  icon: LucideIcon;
}

interface NavGroup {
  th: string;
  en: string;
  items: NavItem[];
}

const NAV_GROUPS: NavGroup[] = [
  {
    th: "ค้นหา",
    en: "Discover",
    items: [
      { href: "/", th: "ภาพรวม", en: "Overview", icon: LayoutDashboard },
      { href: "/renovation", th: "งานรีโนเวท", en: "Renovation", icon: Hammer },
      { href: "/leads", th: "ลูกค้า", en: "Leads", icon: Users },
      { href: "/competitors", th: "คู่แข่ง", en: "Competitors", icon: Radar },
    ],
  },
  {
    th: "วิเคราะห์",
    en: "Analyze",
    items: [
      { href: "/kb", th: "คลังความรู้", en: "Knowledge Base", icon: BookOpen },
      { href: "/agents", th: "เอเจนต์", en: "Agents", icon: Bot },
      { href: "/reports", th: "รายงาน", en: "Reports", icon: FileText },
    ],
  },
  {
    th: "จัดการ",
    en: "Manage",
    items: [{ href: "/settings", th: "ตั้งค่า", en: "Settings", icon: Settings }],
  },
];

export function Sidebar() {
  const pathname = usePathname();
  const isActive = (href: string) =>
    href === "/" ? pathname === "/" : pathname.startsWith(href);

  return (
    <aside className="sticky top-0 hidden h-screen w-64 shrink-0 flex-col border-r border-slate-200 bg-white lg:flex">
      {/* Brand */}
      <div className="flex items-center gap-3 px-5 py-5">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-600 text-white">
          <Radar size={20} />
        </div>
        <div>
          <p className="text-sm font-bold text-slate-900">{t("app.title")}</p>
          <p className="text-xs text-slate-400">{t("app.brand")}</p>
        </div>
      </div>

      {/* Nav groups */}
      <nav className="flex-1 space-y-6 overflow-y-auto px-3 py-2">
        {NAV_GROUPS.map((group) => (
          <div key={group.th}>
            <p className="px-3 pb-2 text-xs font-semibold text-slate-400">
              {group.th} <span className="font-normal text-slate-300">· {group.en}</span>
            </p>
            <ul className="space-y-1">
              {group.items.map((item) => {
                const active = isActive(item.href);
                const Icon = item.icon;
                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      title={item.en}
                      aria-current={active ? "page" : undefined}
                      className={`flex items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium transition-colors ${
                        active
                          ? "bg-blue-50 text-blue-700"
                          : "text-slate-600 hover:bg-slate-50 hover:text-slate-900"
                      }`}
                    >
                      <Icon size={18} className={active ? "text-blue-600" : "text-slate-400"} />
                      {item.th}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>

      {/* Phase footer */}
      <div className="border-t border-slate-100 p-4">
        <div className="rounded-xl bg-slate-50 px-3 py-2.5">
          <p className="text-xs font-semibold text-slate-700">เฟส A — งานรีโนเวท</p>
          <p className="mt-0.5 text-xs text-slate-400">Lipa Noi · Chaweng · เกาะสมุย</p>
        </div>
      </div>
    </aside>
  );
}
