import type {
  Channel,
  CommunicationHealth,
  DecisionStatus,
  Priority,
  ResolutionState,
  TimelineEntry,
} from "./types";
import type { BadgeTone } from "../components/common/Badge";

/** "payment_system" -> "Payment system". The backend has no title/description field on
 * Case (app/domain/entities/case.py) — `topic` (free text, from the policy pack's closed
 * set, or an LLM-classified string outside it) is the closest thing to one, so case titles
 * are derived from it here rather than inventing a backend field. */
export function humanizeTopic(topic: string | null): string {
  if (!topic) return "Untitled case";
  const spaced = topic.replace(/_/g, " ").trim();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

export function caseShortId(id: string): string {
  return id.slice(0, 8);
}

/** There is no description field either — the case's own opening message is the closest
 * real substitute (build_timeline() already surfaces every message chronologically). */
export function firstInboundSummary(timeline: TimelineEntry[]): string | null {
  const first = timeline.find((e) => e.event_type === "message" && e.direction === "inbound");
  return first ? first.summary : null;
}

const PRIORITY_LABEL: Record<Priority, string> = { high: "High", medium: "Medium", low: "Low" };
export function priorityLabel(p: Priority): string {
  return PRIORITY_LABEL[p];
}

const RESOLUTION_LABEL: Record<ResolutionState, string> = {
  open: "Open",
  awaiting_response: "Awaiting reply",
  escalated: "Escalated",
  human_handoff: "Human handoff",
  resolved: "Resolved",
  abandoned: "Abandoned",
};
export function resolutionLabel(s: ResolutionState): string {
  return RESOLUTION_LABEL[s];
}

const HEALTH_LABEL: Record<CommunicationHealth, string> = {
  healthy: "Healthy",
  at_risk: "At risk",
  stalled: "Stalled",
  critical: "Critical",
};
export function healthLabel(h: CommunicationHealth): string {
  return HEALTH_LABEL[h];
}

/** Coarse score for the health meter — the backend's numeric score
 * (CalculateCommunicationHealthNode's `chosen_action.score`) lives on a per-decision record,
 * not on CaseSnapshotDTO, so the list/detail views position the meter from the state enum
 * instead of a number the API doesn't expose at that layer. The exact score is still shown
 * where it IS returned — the "calculate_communication_health" decision's chosen_action. */
const HEALTH_METER: Record<CommunicationHealth, number> = {
  healthy: 90,
  at_risk: 60,
  stalled: 30,
  critical: 10,
};
export function healthMeterValue(h: CommunicationHealth): number {
  return HEALTH_METER[h];
}

const CHANNEL_LABEL: Record<Channel, string> = {
  email: "Email",
  telegram: "Telegram",
  slack: "Slack",
  discord: "Discord",
};
export function channelLabel(c: Channel): string {
  return CHANNEL_LABEL[c];
}

export const CHANNEL_COLOR: Record<Channel, string> = {
  email: "var(--color-channel-email)",
  telegram: "var(--color-channel-telegram)",
  slack: "var(--color-channel-slack)",
  discord: "var(--color-channel-discord)",
};

const RELATIVE_UNITS: [number, string][] = [
  [60, "s"],
  [60, "m"],
  [24, "h"],
  [7, "d"],
];

export function formatRelative(iso: string | null): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";
  const now = Date.now();
  const diffMs = now - then;
  const future = diffMs < 0;
  let value = Math.abs(diffMs) / 1000;
  let unit = "s";
  for (const [factor, u] of RELATIVE_UNITS) {
    if (value < factor) {
      unit = u;
      break;
    }
    value /= factor;
    unit = u;
  }
  const rounded = Math.max(1, Math.round(value));
  if (unit === "s" && rounded < 5) return future ? "shortly" : "just now";
  return future ? `in ${rounded}${unit}` : `${rounded}${unit} ago`;
}

export function formatTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

export function formatDateTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function cx(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}

/** Status visual language (spec §20) — deliberately restrained: green reserved for
 * resolved/healthy, red for danger states, amber for warnings, everything else neutral. */
const PRIORITY_TONE: Record<Priority, BadgeTone> = { high: "danger", medium: "warning", low: "neutral" };
export function priorityTone(p: Priority): BadgeTone {
  return PRIORITY_TONE[p];
}

const RESOLUTION_TONE: Record<ResolutionState, BadgeTone> = {
  open: "neutral",
  awaiting_response: "info",
  escalated: "warning",
  human_handoff: "warning",
  resolved: "success",
  abandoned: "neutral",
};
export function resolutionTone(s: ResolutionState): BadgeTone {
  return RESOLUTION_TONE[s];
}

const HEALTH_TONE: Record<CommunicationHealth, BadgeTone> = {
  healthy: "success",
  at_risk: "warning",
  stalled: "danger",
  critical: "danger",
};
export function healthTone(h: CommunicationHealth): BadgeTone {
  return HEALTH_TONE[h];
}

const DECISION_STATUS_TONE: Record<DecisionStatus, BadgeTone> = {
  pending: "neutral",
  executing: "info",
  success: "success",
  failed: "danger",
};
export function decisionStatusTone(s: DecisionStatus): BadgeTone {
  return DECISION_STATUS_TONE[s];
}
