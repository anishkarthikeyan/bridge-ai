import { ArrowRight } from "lucide-react";

interface ChannelTransitionProps {
  role: string;
  participant: string;
  channel: string;
  reason: string;
}

/** The single most important visual moment in the product (spec §11): a missing stakeholder
 * being routed onto a new channel. Inline and operational, not a graph visualization. */
export function ChannelTransition({ role, participant, channel, reason }: ChannelTransitionProps) {
  return (
    <div className="rounded-md border border-accent/30 bg-accent/5 px-3 py-2.5">
      <div className="text-[10px] font-semibold tracking-wide text-accent uppercase">
        Channel transition
      </div>
      <div className="mt-1.5 flex items-center gap-2 text-[13px] font-medium text-text-primary">
        <span>{role}</span>
        <ArrowRight size={13} className="text-text-muted" />
        <span>{participant}</span>
        <span className="text-text-muted">·</span>
        <span>{channel}</span>
      </div>
      <div className="mt-1 text-[12px] text-text-secondary">{reason}</div>
    </div>
  );
}
