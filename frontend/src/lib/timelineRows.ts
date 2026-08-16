import type { Channel, Decision, MessageDirection, TimelineEntry } from "./types";

/**
 * Bridges GET /cases/{id}/timeline and GET /cases/{id}/decisions into one chronological feed.
 *
 * TimelineEntryDTO (the /timeline endpoint) intentionally carries only `summary` — it has no
 * `chosen_action` or `confidence`, so it can't drive the richer per-node rendering the case
 * page needs (missing roles, priority value, drafted text, etc.). DecisionDTO (the /decisions
 * endpoint) has all of that, plus a stable `id` — so decision-type rows are sourced from
 * there. Message-type rows have no equivalent on /decisions, so those still come from
 * /timeline (today this is always empty in practice — see decisionPresentation.ts's
 * `receive_message`/`wait_for_reply` cases for why the human/reply side of the story is
 * rendered from Decision rows instead; MessageRepositoryPort is defined but, per
 * app/brain/nodes/calculate_communication_health.py's own docstring, "not wired into the
 * brain yet" — this keeps the UI correct today and automatically starts rendering real
 * message content the moment that changes, with no frontend change required).
 */
export type TimelineRow =
  | {
      kind: "message";
      key: string;
      timestamp: string | null;
      channel: Channel | null;
      direction: MessageDirection | null;
      summary: string;
    }
  | { kind: "decision"; key: string; timestamp: string | null; decision: Decision };

export function buildTimelineRows(decisions: Decision[], timeline: TimelineEntry[]): TimelineRow[] {
  const rows: TimelineRow[] = [];

  for (const d of decisions) {
    rows.push({ kind: "decision", key: d.id, timestamp: d.created_at, decision: d });
  }

  for (const [i, entry] of timeline.entries()) {
    if (entry.event_type !== "message") continue;
    rows.push({
      kind: "message",
      key: `msg-${i}-${entry.timestamp ?? i}`,
      timestamp: entry.timestamp,
      channel: entry.channel,
      direction: entry.direction,
      summary: entry.summary,
    });
  }

  rows.sort((a, b) => {
    const ta = a.timestamp ? new Date(a.timestamp).getTime() : -Infinity;
    const tb = b.timestamp ? new Date(b.timestamp).getTime() : -Infinity;
    return ta - tb;
  });

  return rows;
}
