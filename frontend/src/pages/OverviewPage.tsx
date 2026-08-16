import { Link } from "react-router-dom";
import { getDashboardSummary } from "../lib/api";
import { useFetch } from "../lib/useFetch";
import { LoadingState } from "../components/common/LoadingState";
import { ErrorState } from "../components/common/ErrorState";
import { EmptyState } from "../components/common/EmptyState";
import { Badge } from "../components/common/Badge";
import {
  caseShortId,
  decisionStatusTone,
  formatRelative,
  priorityLabel,
} from "../lib/utils";
import { describeDecision } from "../lib/decisionPresentation";
import { LayoutGrid } from "lucide-react";

const POLL_MS = 5000;

export function OverviewPage() {
  const { data, error, isLoading, refetch } = useFetch(getDashboardSummary, "summary", {
    pollMs: POLL_MS,
  });

  return (
    <div className="mx-auto max-w-300 px-8 py-8">
      <header className="mb-6">
        <h1 className="text-[26px] font-semibold text-text-primary">Overview</h1>
        <p className="mt-1 text-[13px] text-text-secondary">A snapshot of every open case</p>
      </header>

      {isLoading ? (
        <LoadingState rows={4} />
      ) : error || !data ? (
        <ErrorState message={error ?? "Unable to load the dashboard summary."} onRetry={refetch} />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 coll:grid-cols-4">
            <StatCard label="Open cases" value={data.total_open_cases} />
            <StatCard label="Needs attention" value={data.cases_due_for_followup} />
            <StatCard label="High priority" value={data.high_priority_cases} />
            <StatCard label="Resolved" value={data.total_resolved_cases} />
          </div>

          <p className="mt-3 text-[12px] text-text-muted">
            {data.critical_cases} critical · {data.cases_escalated} escalated ·{" "}
            {data.cases_waiting_for_reply} waiting for reply
          </p>

          <div className="mt-8 grid grid-cols-1 gap-6 coll:grid-cols-[1fr_320px]">
            <section>
              <h2 className="mb-3 text-[15px] font-semibold text-text-primary">Recent activity</h2>
              {data.recent_decisions.length === 0 ? (
                <EmptyState
                  icon={LayoutGrid}
                  title="No activity yet"
                  description="Bridge AI is waiting for communication."
                />
              ) : (
                <div className="overflow-hidden rounded-md border border-border bg-surface">
                  <table className="w-full border-collapse text-left text-[13px]">
                    <tbody>
                      {data.recent_decisions.map((d) => {
                        const info = describeDecision(d);
                        return (
                          <tr key={d.id} className="border-b border-border last:border-b-0">
                            <td className="px-3 py-2.5 text-text-muted whitespace-nowrap">
                              {formatRelative(d.created_at)}
                            </td>
                            <td className="px-3 py-2.5">
                              <Link
                                to={`/cases/${d.case_id}`}
                                className="text-text-primary hover:text-accent"
                              >
                                CASE-{caseShortId(d.case_id)}
                              </Link>
                            </td>
                            <td className="px-3 py-2.5 text-text-secondary">{info.title}</td>
                            <td className="px-3 py-2.5">
                              <Badge tone={decisionStatusTone(d.status)}>{d.status}</Badge>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </section>

            <section>
              <h2 className="mb-3 text-[15px] font-semibold text-text-primary">
                Priority distribution
              </h2>
              <div className="rounded-md border border-border bg-surface p-4">
                {(() => {
                  const max = Math.max(
                    data.high_priority_cases,
                    data.medium_priority_cases,
                    data.low_priority_cases,
                    1,
                  );
                  return (
                    <>
                      <PriorityBar
                        label={priorityLabel("high")}
                        value={data.high_priority_cases}
                        max={max}
                        tone="danger"
                      />
                      <PriorityBar
                        label={priorityLabel("medium")}
                        value={data.medium_priority_cases}
                        max={max}
                        tone="warning"
                      />
                      <PriorityBar
                        label={priorityLabel("low")}
                        value={data.low_priority_cases}
                        max={max}
                        tone="neutral"
                      />
                    </>
                  );
                })()}
              </div>
            </section>
          </div>
        </>
      )}
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md border border-border bg-surface px-4 py-3.5">
      <div className="text-[24px] font-semibold text-text-primary">{value}</div>
      <div className="mt-0.5 text-[12px] text-text-secondary">{label}</div>
    </div>
  );
}

const BAR_COLOR: Record<string, string> = {
  danger: "bg-danger",
  warning: "bg-warning",
  neutral: "bg-text-muted",
};

function PriorityBar({
  label,
  value,
  max,
  tone,
}: {
  label: string;
  value: number;
  max: number;
  tone: string;
}) {
  return (
    <div className="mb-3 last:mb-0">
      <div className="mb-1 flex items-center justify-between text-[12px]">
        <span className="text-text-secondary">{label}</span>
        <span className="text-text-primary">{value}</span>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-secondary">
        <div
          className={`h-full rounded-full ${BAR_COLOR[tone]}`}
          style={{ width: `${(value / max) * 100}%` }}
        />
      </div>
    </div>
  );
}
