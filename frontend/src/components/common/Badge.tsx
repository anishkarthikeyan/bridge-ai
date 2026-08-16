import type { ReactNode } from "react";
import { cx } from "../../lib/utils";

export type BadgeTone = "neutral" | "success" | "warning" | "danger" | "info" | "accent";

const TONE_CLASSES: Record<BadgeTone, string> = {
  neutral: "bg-surface-secondary text-text-secondary border-border",
  success: "bg-success/10 text-success border-success/25",
  warning: "bg-warning/10 text-warning border-warning/25",
  danger: "bg-danger/10 text-danger border-danger/25",
  info: "bg-info/10 text-info border-info/25",
  accent: "bg-accent/10 text-accent border-accent/25",
};

interface BadgeProps {
  tone?: BadgeTone;
  children: ReactNode;
  className?: string;
}

/** Status is never color-only — the label text is the primary signal, tone is reinforcement
 * (spec §24: "no color-only status indication"). */
export function Badge({ tone = "neutral", children, className }: BadgeProps) {
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1 rounded-sm border px-1.5 py-0.5 text-[11px] font-medium uppercase tracking-wide leading-none",
        TONE_CLASSES[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}
