import Link from "next/link";
import { ArrowRight, Radar } from "lucide-react";

/**
 * Hero "signal" card — one primary stat + CTA, radar-ring decoration.
 */
export function HeroSignalCard({
  title,
  headline,
  description,
  ctaHref,
  ctaLabel,
}: {
  title: string;
  headline: string;
  description: string;
  ctaHref: string;
  ctaLabel: string;
}) {
  return (
    <section className="relative overflow-hidden rounded-2xl bg-blue-600 p-6 text-white sm:p-8">
      {/* Radar rings */}
      <div aria-hidden className="pointer-events-none absolute -right-16 -top-24 h-72 w-72 rounded-full border border-white/15" />
      <div aria-hidden className="pointer-events-none absolute -right-4 -top-12 h-48 w-48 rounded-full border border-white/15" />
      <div aria-hidden className="pointer-events-none absolute right-8 top-0 h-24 w-24 rounded-full border border-white/20" />

      <div className="relative">
        <div className="flex items-center gap-2 text-blue-100">
          <Radar size={18} />
          <span className="text-sm font-medium">{title}</span>
        </div>
        <p className="mt-3 text-4xl font-bold tracking-tight">{headline}</p>
        <p className="mt-2 max-w-xl text-sm leading-relaxed text-blue-100">{description}</p>
        <Link
          href={ctaHref}
          className="mt-5 inline-flex items-center gap-2 rounded-xl bg-white px-4 py-2.5 text-sm font-semibold text-blue-700 transition-colors hover:bg-blue-50"
        >
          {ctaLabel}
          <ArrowRight size={16} />
        </Link>
      </div>
    </section>
  );
}
