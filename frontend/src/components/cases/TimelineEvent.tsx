import { Mail, MessageCircle, Send, AlertTriangle, CheckCircle2, ArrowRightLeft } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { TimelineRow } from "../../lib/timelineRows";
import { describeDecision } from "../../lib/decisionPresentation";
import { CHANNEL_COLOR, channelLabel, cx, decisionStatusTone, formatTime } from "../../lib/utils";
import { Badge } from "../common/Badge";
import { AgentEvent, type AgentEventTone } from "./AgentEvent";
import { ChannelTransition } from "./ChannelTransition";
import type { Channel, Decision } from "../../lib/types";

const CHANNEL_ICON: Record<Channel, LucideIcon> = {
  email: Mail,
  telegram: MessageCircle,
  slack: MessageCircle,
  discord: MessageCircle,
};

const CATEGORY_ICON: Record<string, LucideIcon> = {
  reasoning: ArrowRightLeft,
  outbound: Send,
  escalation: AlertTriangle,
  resolution: CheckCircle2,
};

const CATEGORY_TONE: Record<string, AgentEventTone> = {
  reasoning: "neutral",
  outbound: "accent",
  escalation: "warning",
  resolution: "success",
};

const CATEGORY_MARKER: Record<string, string> = {
  message: "bg-text-muted",
  reasoning: "bg-border-strong",
  channel_transition: "bg-accent",
  outbound: "bg-accent",
  escalation: "bg-warning",
  resolution: "bg-success",
};

interface TimelineEventProps {
  row: TimelineRow;
  isNew: boolean;
}

export function TimelineEvent({ row, isNew }: TimelineEventProps) {
  const category = row.kind === "message" ? "message" : describeDecision(row.decision).category;

  return (
    <div className={cx("flex gap-3", isNew && "animate-entry")}>
      <div className="w-14 shrink-0 pt-2 text-right text-[11px] text-text-muted">
        {formatTime(row.timestamp)}
      </div>
      <div className="relative flex w-6 shrink-0 justify-center">
        <span className={cx("mt-2.5 h-2 w-2 rounded-full ring-4 ring-bg", CATEGORY_MARKER[category])} />
      </div>
      <div className="min-w-0 flex-1 pb-1">
        {row.kind === "message" ? <MessageRow row={row} /> : <DecisionRow decision={row.decision} />}
      </div>
    </div>
  );
}

function MessageRow({ row }: { row: Extract<TimelineRow, { kind: "message" }> }) {
  const Icon = row.channel ? CHANNEL_ICON[row.channel] : MessageCircle;
  const color = row.channel ? CHANNEL_COLOR[row.channel] : undefined;
  return (
    <div className="rounded-md border border-border bg-surface px-3 py-2.5">
      <div className="flex items-center gap-1.5 text-[10px] font-semibold tracking-wide uppercase" style={{ color }}>
        <Icon size={12} strokeWidth={2} />
        {row.channel ? channelLabel(row.channel) : "Message"}
        <span className="text-text-muted normal-case">
          · {row.direction === "outbound" ? "Outbound" : "Inbound"}
        </span>
      </div>
      <p className="mt-1 text-[13px] text-text-primary">{row.summary}</p>
    </div>
  );
}

function DecisionRow({ decision: d }: { decision: Decision }) {
  const info = describeDecision(d);

  if (info.category === "channel_transition" && info.transition) {
    return <ChannelTransition {...info.transition} />;
  }

  const Icon = CATEGORY_ICON[info.category] ?? ArrowRightLeft;
  const tone = CATEGORY_TONE[info.category] ?? "neutral";

  return (
    <AgentEvent icon={Icon} tone={tone} title={info.title} detail={info.detail}>
      {info.draftedMessage ? (
        <blockquote className="mt-1.5 border-l-2 border-border-strong pl-2 text-[12px] text-text-secondary italic">
          “{info.draftedMessage}”
        </blockquote>
      ) : null}
      {d.node_name === "dispatch" ? (
        <div className="mt-1.5">
          <Badge tone={decisionStatusTone(d.status)}>{d.status}</Badge>
        </div>
      ) : null}
    </AgentEvent>
  );
}
