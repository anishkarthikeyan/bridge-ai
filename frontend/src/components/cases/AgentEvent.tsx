import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { cx } from "../../lib/utils";

export type AgentEventTone = "neutral" | "accent" | "warning" | "success" | "danger";

const TONE_ICON: Record<AgentEventTone, string> = {
  neutral: "text-text-muted",
  accent: "text-accent",
  warning: "text-warning",
  success: "text-success",
  danger: "text-danger",
};

const TONE_BORDER: Record<AgentEventTone, string> = {
  neutral: "border-border",
  accent: "border-accent/30",
  warning: "border-warning/30",
  success: "border-success/30",
  danger: "border-danger/30",
};

interface AgentEventProps {
  icon: LucideIcon;
  tone?: AgentEventTone;
  title: string;
  detail?: string;
  children?: ReactNode;
}

/** The "subtle, technical" agent-reasoning box (spec §10) — a title, one supporting line
 * built entirely from real Decision fields, and never anything resembling chain-of-thought. */
export function AgentEvent({ icon: Icon, tone = "neutral", title, detail, children }: AgentEventProps) {
  return (
    <div className={cx("rounded-md border bg-surface px-3 py-2.5", TONE_BORDER[tone])}>
      <div className="flex items-center gap-1.5 text-[10px] font-semibold tracking-wide text-text-muted uppercase">
        <Icon size={12} strokeWidth={2} className={TONE_ICON[tone]} />
        Bridge AI
      </div>
      <div className="mt-1 text-[13px] font-medium text-text-primary">{title}</div>
      {detail ? <div className="mt-0.5 text-[12px] text-text-secondary">{detail}</div> : null}
      {children}
    </div>
  );
}
