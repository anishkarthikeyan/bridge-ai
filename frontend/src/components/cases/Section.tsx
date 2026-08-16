import type { ReactNode } from "react";

interface SectionProps {
  title: string;
  children: ReactNode;
}

/** One case-intelligence block — "Keep each section separated by subtle borders" (spec §12). */
export function Section({ title, children }: SectionProps) {
  return (
    <div className="border-t border-border px-4 py-3.5 first:border-t-0 first:pt-0">
      <h3 className="text-[11px] font-semibold tracking-wide text-text-muted uppercase">{title}</h3>
      <div className="mt-2">{children}</div>
    </div>
  );
}
