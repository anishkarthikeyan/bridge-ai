import { Link } from "react-router-dom";
import { Activity } from "lucide-react";
import { getDashboardSummary } from "../lib/api";
import { useFetch } from "../lib/useFetch";
import { describeDecision } from "../lib/decisionPresentation";
import type { Channel, RecentDecision } from "../lib/types";
import { caseShortId, channelLabel, decisionStatusTone, formatDateTime } from "../lib/utils";
import { Badge } from "../components/common/Badge";
import { LoadingState } from "../components/common/LoadingState";
import { ErrorState } from "../components/common/ErrorState";
import { EmptyState } from "../components/common/EmptyState";

const POLL_MS = 4000;

/** Not every decision carries a channel (e.g. classify_topic doesn't) — this reads only the
 * real fields already present on chosen_action, never invents one. */
function channelForDecision(d: RecentDecision): Channel | null {
  const action = d.chosen_action;
  const value = action.channel ?? action.selected_channel;
  return typeof value === "string" ? (value as Channel) : null;
}

export function ActivityPage() {
  const { data, error, isLoading, refetch } = useFetch(getDashboardSummary, "activity", {
    pollMs: POLL_MS,
  });

  return (
    <div className="mx-auto max-w-300 px-8 py-8">
      <header className="mb-6">
        <h1 className="text-[26px] font-semibold text-text-primary">Activity</h1>
        <p className="mt-1 text-[13px] text-text-secondary">
          The most recent reasoning and dispatch events across every case
        </p>
      </header>

      {isLoading ? (
        <LoadingState rows={6} />
      ) : error || !data ? (
        <ErrorState message={error ?? "Unable to load activity."} onRetry={refetch} />
      ) : data.recent_decisions.length === 0 ? (
        <EmptyState
          icon={Activity}
          title="No activity yet"
          description="Bridge AI is waiting for communication."
        />
      ) : (
        <div className="overflow-hidden rounded-md border border-border bg-surface">
          <table className="w-full border-collapse text-left text-[13px]">
            <thead>
              <tr className="border-b border-border text-[11px] font-medium tracking-wide text-text-muted uppercase">
                <th className="px-4 py-2.5 font-medium">Time</th>
                <th className="px-4 py-2.5 font-medium">Case</th>
                <th className="px-4 py-2.5 font-medium">Event</th>
                <th className="px-4 py-2.5 font-medium">Channel</th>
                <th className="px-4 py-2.5 font-medium">Result</th>
              </tr>
            </thead>
            <tbody>
              {data.recent_decisions.map((d) => {
                const info = describeDecision(d);
                const channel = channelForDecision(d);
                return (
                  <tr key={d.id} className="border-b border-border last:border-b-0">
                    <td className="px-4 py-3 whitespace-nowrap text-text-muted">
                      {formatDateTime(d.created_at)}
                    </td>
                    <td className="px-4 py-3">
                      <Link to={`/cases/${d.case_id}`} className="text-text-primary hover:text-accent">
                        CASE-{caseShortId(d.case_id)}
                      </Link>
                    </td>
                    <td className="px-4 py-3 text-text-secondary">{info.title}</td>
                    <td className="px-4 py-3 text-text-secondary">
                      {channel ? channelLabel(channel) : "—"}
                    </td>
                    <td className="px-4 py-3">
                      <Badge tone={decisionStatusTone(d.status)}>{d.status}</Badge>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
