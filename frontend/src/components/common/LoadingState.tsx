import { cx } from "../../lib/utils";

/** Subtle skeleton — no spinners, no "AI thinking" language (spec §19). */
export function LoadingState({ rows = 4, className }: { rows?: number; className?: string }) {
  return (
    <div className={cx("space-y-2", className)} role="status" aria-label="Loading">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-11 animate-pulse rounded-md bg-surface-secondary" />
      ))}
    </div>
  );
}
