import type { Decision } from "./types";
import { channelLabel, humanizeTopic, priorityLabel } from "./utils";
import type { Priority, Channel } from "./types";

export type DecisionCategory =
  | "message"
  | "reasoning"
  | "channel_transition"
  | "outbound"
  | "escalation"
  | "resolution";

export interface DecisionPresentation {
  category: DecisionCategory;
  title: string;
  /** A short supporting line — always built from real `chosen_action`/`reasoning_summary`
   * fields already returned by GET /cases/{id}/decisions, never invented. */
  detail?: string;
  /** For channel_transition only: the role/participant/channel it resolved to. */
  transition?: { role: string; participant: string; channel: string; reason: string };
  /** For outbound (generate_message) only — the real drafted text. */
  draftedMessage?: string;
}

function pct(confidence: number | null): string {
  return confidence === null ? "" : ` · ${Math.round(confidence * 100)}% confidence`;
}

const str = (v: unknown): string => (typeof v === "string" ? v : "");
const num = (v: unknown): number | null => (typeof v === "number" ? v : null);
const arr = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x) => typeof x === "string") : []);

/** node_name -> presentation. One real Decision in, one rendering decision out — every
 * field used here comes straight from DecisionDTO (id, node_name, status, reasoning_summary,
 * chosen_action, confidence, created_at); see app/application/dto/case_snapshot_dto.py. */
export function describeDecision(d: Decision): DecisionPresentation {
  const action = d.chosen_action;

  switch (d.node_name) {
    case "receive_message":
      return { category: "message", title: "Message received", detail: d.reasoning_summary };

    case "wait_for_reply":
      return { category: "message", title: "Reply received", detail: d.reasoning_summary };

    case "extract_intent":
      return {
        category: "reasoning",
        title: "Intent detected",
        detail: `${str(action.intent) || "unknown"}${pct(d.confidence)}`,
      };

    case "extract_entities": {
      const people = arr(action.people);
      const roles = arr(action.mentioned_roles);
      const dates = arr(action.dates);
      return {
        category: "reasoning",
        title: "Entities extracted",
        detail: `${people.length} people · ${roles.length} role(s) mentioned · ${dates.length} date(s)`,
      };
    }

    case "classify_topic":
      return {
        category: "reasoning",
        title: "Topic classified",
        detail: `${humanizeTopic(str(action.topic) || null)}${pct(d.confidence)}`,
      };

    case "load_policy": {
      const roles = arr(action.required_roles);
      return {
        category: "reasoning",
        title: "Policy loaded",
        detail: roles.length ? `Requires ${roles.join(", ")}` : "No required roles for this topic",
      };
    }

    case "detect_missing_stakeholders": {
      const missing = arr(action.missing_roles);
      const present = arr(action.present_roles);
      return {
        category: "reasoning",
        title: "Missing stakeholder analysis",
        detail: missing.length
          ? `Missing ${missing.join(", ")}${present.length ? ` · present: ${present.join(", ")}` : ""}`
          : "All required roles present",
      };
    }

    case "calculate_communication_health":
      return {
        category: "reasoning",
        title: "Communication health calculated",
        detail: `${num(action.score) ?? "—"}/100 → ${str(action.state).replace("_", " ")}`,
      };

    case "calculate_priority":
      return {
        category: "reasoning",
        title: "Priority calculated",
        detail: `${priorityLabel((str(action.priority) || "medium") as Priority)}`,
      };

    case "resolution_evaluator":
      return {
        category: "reasoning",
        title: "Resolution evaluated",
        detail: `Outcome: ${str(action.outcome).replace("_", " ")}`,
      };

    case "select_channel":
      if (action.path === "role_resolution") {
        const role = str(action.role);
        const participant = str(action.participant);
        const channel = str(action.selected_channel);
        return {
          category: "channel_transition",
          title: "Missing stakeholder routed",
          transition: {
            role,
            participant,
            channel: channel ? channelLabel(channel as Channel) : "—",
            reason: d.reasoning_summary,
          },
        };
      }
      return {
        category: "reasoning",
        title: "Channel selected",
        detail: action.selected_channel
          ? `${channelLabel(str(action.selected_channel) as Channel)} (${str(action.style)})`
          : `No channel available (${str(action.style)})`,
      };

    case "generate_message":
      return {
        category: "outbound",
        title: `Message drafted for ${str(action.recipient) || "recipient"}`,
        detail: `via ${channelLabel((str(action.channel) || "email") as Channel)}`,
        draftedMessage: str(action.message),
      };

    case "create_decision":
      return {
        category: "outbound",
        title: `Queued to send to ${str(action.recipient_name) || "recipient"}`,
        detail: `${channelLabel((str(action.channel) || "email") as Channel)} · priority ${priorityLabel((str(action.priority) || "medium") as Priority)}`,
      };

    case "dispatch":
      return {
        category: "outbound",
        title: d.status === "success" ? "Dispatch succeeded" : "Dispatch failed",
        detail: str(action.channel) ? channelLabel(str(action.channel) as Channel) : undefined,
      };

    case "escalate":
      return { category: "escalation", title: "Case escalated", detail: d.reasoning_summary };

    case "resolve_case":
      return { category: "resolution", title: "Case resolved", detail: d.reasoning_summary };

    default:
      return { category: "reasoning", title: d.node_name, detail: d.reasoning_summary };
  }
}
