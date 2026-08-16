import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Search } from "lucide-react";
import { listCases } from "../lib/api";
import { useFetch } from "../lib/useFetch";
import type { Priority, ResolutionState } from "../lib/types";
import {
  caseShortId,
  formatRelative,
  healthLabel,
  healthTone,
  humanizeTopic,
  priorityLabel,
  priorityTone,
  resolutionLabel,
  resolutionTone,
} from "../lib/utils";
import { Badge } from "../components/common/Badge";
import { EmptyState } from "../components/common/EmptyState";
import { ErrorState } from "../components/common/ErrorState";
import { LoadingState } from "../components/common/LoadingState";

const STATUS_OPTIONS: { value: ResolutionState | ""; label: string }[] = [
  { value: "", label: "All statuses" },
  { value: "open", label: "Open" },
  { value: "awaiting_response", label: "Awaiting reply" },
  { value: "escalated", label: "Escalated" },
  { value: "human_handoff", label: "Human handoff" },
  { value: "resolved", label: "Resolved" },
  { value: "abandoned", label: "Abandoned" },
];

const PRIORITY_OPTIONS: { value: Priority | ""; label: string }[] = [
  { value: "", label: "All priorities" },
  { value: "high", label: "High" },
  { value: "medium", label: "Medium" },
  { value: "low", label: "Low" },
];

export function CasesPage() {
  const navigate = useNavigate();
  const [status, setStatus] = useState<ResolutionState | "">("");
  const [priority, setPriority] = useState<Priority | "">("");
  const [search, setSearch] = useState("");

  const filterKey = `${status}|${priority}`;
  const { data, error, isLoading, refetch } = useFetch(
    () =>
      listCases({
        status: status || undefined,
        priority: priority || undefined,
        limit: 200,
      }),
    filterKey,
    { pollMs: 5000 },
  );

  const items = useMemo(() => {
    const all = data?.items ?? [];
    const q = search.trim().toLowerCase();
    if (!q) return all;
    return all.filter(
      (c) =>
        humanizeTopic(c.topic).toLowerCase().includes(q) ||
        (c.topic ?? "").toLowerCase().includes(q) ||
        c.id.toLowerCase().includes(q),
    );
  }, [data, search]);

  return (
    <div className="mx-auto max-w-300 px-8 py-8">
      <header className="mb-6">
        <h1 className="text-[26px] font-semibold text-text-primary">Cases</h1>
        <p className="mt-1 text-[13px] text-text-secondary">All active communication cases</p>
      </header>

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="relative">
          <Search
            size={14}
            className="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-text-muted"
          />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search cases…"
            aria-label="Search cases"
            className="w-56 rounded-md border border-border bg-surface py-1.5 pr-3 pl-8 text-[13px] text-text-primary placeholder:text-text-muted focus:border-border-strong"
          />
        </div>

        <select
          value={status}
          onChange={(e) => setStatus(e.target.value as ResolutionState | "")}
          aria-label="Filter by status"
          className="rounded-md border border-border bg-surface px-2.5 py-1.5 text-[13px] text-text-primary"
        >
          {STATUS_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>

        <select
          value={priority}
          onChange={(e) => setPriority(e.target.value as Priority | "")}
          aria-label="Filter by priority"
          className="rounded-md border border-border bg-surface px-2.5 py-1.5 text-[13px] text-text-primary"
        >
          {PRIORITY_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>

        {data ? (
          <span className="ml-auto text-[12px] text-text-muted">
            {items.length} of {data.total}
          </span>
        ) : null}
      </div>

      {isLoading ? (
        <LoadingState rows={6} />
      ) : error ? (
        <ErrorState message={error} onRetry={refetch} />
      ) : items.length === 0 ? (
        <EmptyState
          title="No active cases"
          description="Bridge AI is waiting for communication."
        />
      ) : (
        <div className="overflow-hidden rounded-md border border-border bg-surface">
          <table className="w-full border-collapse text-left text-[13px]">
            <thead>
              <tr className="border-b border-border text-[11px] font-medium tracking-wide text-text-muted uppercase">
                <th className="px-4 py-2.5 font-medium">Case</th>
                <th className="px-4 py-2.5 font-medium">Topic</th>
                <th className="px-4 py-2.5 font-medium">Status</th>
                <th className="px-4 py-2.5 font-medium">Priority</th>
                <th className="px-4 py-2.5 font-medium">Health</th>
                <th className="px-4 py-2.5 font-medium">Missing</th>
                <th className="px-4 py-2.5 font-medium">Updated</th>
              </tr>
            </thead>
            <tbody>
              {items.map((c) => (
                <tr
                  key={c.id}
                  tabIndex={0}
                  role="link"
                  aria-label={`Open case ${humanizeTopic(c.topic)}, CASE-${caseShortId(c.id)}`}
                  onClick={() => navigate(`/cases/${c.id}`)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      navigate(`/cases/${c.id}`);
                    }
                  }}
                  className="cursor-pointer border-b border-border last:border-b-0 transition-colors hover:bg-surface-secondary focus-visible:bg-surface-secondary"
                >
                  <td className="px-4 py-3">
                    <div className="font-medium text-text-primary">{humanizeTopic(c.topic)}</div>
                    <div className="text-[11px] text-text-muted">CASE-{caseShortId(c.id)}</div>
                  </td>
                  <td className="px-4 py-3 text-text-secondary">{c.topic ?? "—"}</td>
                  <td className="px-4 py-3">
                    <Badge tone={resolutionTone(c.resolution_status)}>
                      {resolutionLabel(c.resolution_status)}
                    </Badge>
                  </td>
                  <td className="px-4 py-3">
                    <Badge tone={priorityTone(c.priority)}>{priorityLabel(c.priority)}</Badge>
                  </td>
                  <td className="px-4 py-3">
                    <Badge tone={healthTone(c.communication_health)}>
                      {healthLabel(c.communication_health)}
                    </Badge>
                  </td>
                  <td className="px-4 py-3 text-text-secondary">
                    {c.missing_roles.length > 0 ? (
                      <span>{c.missing_roles.length} missing</span>
                    ) : (
                      <span className="text-text-muted">All present</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-text-muted">{formatRelative(c.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
