/**
 * Mirrors app/application/dto/case_snapshot_dto.py exactly — field names, optionality, and
 * the closed enum sets in app/domain/value_objects/*.py. Do not add fields the backend does
 * not return; derive presentation-only values in components instead (see lib/utils.ts).
 */

export type Priority = "high" | "medium" | "low";

export type ResolutionState =
  | "open"
  | "awaiting_response"
  | "escalated"
  | "human_handoff"
  | "resolved"
  | "abandoned";

export type CommunicationHealth = "healthy" | "at_risk" | "stalled" | "critical";

export type Channel = "email" | "telegram" | "slack" | "discord";

export type DecisionStatus = "pending" | "executing" | "success" | "failed";

export type MessageDirection = "inbound" | "outbound";

export type ParticipantSource = "explicit" | "inferred";

export interface ParticipantSnapshot {
  id: string;
  name: string;
  role: string | null;
  email: string | null;
  telegram_handle: string | null;
  source: ParticipantSource;
}

export interface TimelineEntry {
  event_type: "message" | "decision";
  timestamp: string | null;
  summary: string;
  channel: Channel | null;
  direction: MessageDirection | null;
  node_name: string | null;
  status: DecisionStatus | null;
}

export interface CaseListItem {
  id: string;
  topic: string | null;
  priority: Priority;
  resolution_status: ResolutionState;
  communication_health: CommunicationHealth;
  missing_roles: string[];
  attempt_count: number;
  next_check_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface CaseListResponse {
  items: CaseListItem[];
  total: number;
  limit: number | null;
  offset: number;
}

export interface CaseSnapshot {
  id: string;
  topic: string | null;
  priority: Priority;
  resolution_status: ResolutionState;
  communication_health: CommunicationHealth;
  required_roles: string[];
  missing_roles: string[];
  participants: ParticipantSnapshot[];
  channels_used: Channel[];
  attempt_count: number;
  next_check_at: string | null;
  timeline: TimelineEntry[];
  created_at: string | null;
  updated_at: string | null;
}

export interface Decision {
  id: string;
  node_name: string;
  status: DecisionStatus;
  reasoning_summary: string;
  chosen_action: Record<string, unknown>;
  confidence: number | null;
  executed: boolean;
  created_at: string | null;
}

export interface RecentDecision extends Decision {
  case_id: string;
}

export interface DashboardSummary {
  total_open_cases: number;
  total_resolved_cases: number;
  critical_cases: number;
  high_priority_cases: number;
  medium_priority_cases: number;
  low_priority_cases: number;
  cases_waiting_for_reply: number;
  cases_due_for_followup: number;
  cases_escalated: number;
  recent_decisions: RecentDecision[];
}
