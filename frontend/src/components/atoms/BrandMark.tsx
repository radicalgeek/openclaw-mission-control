"use client";

import { useBranding } from "@/lib/branding";

export function BrandMark() {
  const branding = useBranding();
  return (
    <div className="flex items-center gap-2.5">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={branding.logoPath}
        alt={branding.fullTitle}
        className="h-14 w-auto object-contain"
      />
      <span className="text-sm font-semibold leading-tight tracking-tight text-[color:var(--text)]">
        {branding.productName}
      </span>
    </div>
  );
}
