import { useParams } from "react-router-dom";
import { useMemo } from "react";
import { getCase, getCaseDecisions, getCaseTimeline } from "../lib/api";
import { useFetch } from "../lib/useFetch";
import { buildTimelineRows } from "../lib/timelineRows";
import { firstInboundSummary } from "../lib/utils";
import { CaseHeader } from "../components/cases/CaseHeader";
import { CaseTimeline } from "../components/cases/CaseTimeline";
import { Section } from "../components/cases/Section";
import { StakeholderList } from "../components/cases/StakeholderList";
import { CaseHealth } from "../components/cases/CaseHealth";
import { CasePriority } from "../components/cases/CasePriority";
import { FollowUpStatus } from "../components/cases/FollowUpStatus";
import { Badge } from "../components/common/Badge";
import { LoadingState } from "../components/common/LoadingState";
import { ErrorState } from "../components/common/ErrorState";
import { channelLabel, resolutionLabel, resolutionTone } from "../lib/utils";

const POLL_MS = 4000;

export function CaseDetailPage() {
  const { id } = useParams<{ id: string }>();
  const caseId = id ?? "";

  const caseFetch = useFetch(() => getCase(caseId), caseId, { pollMs: POLL_MS });
  const timelineFetch = useFetch(() => getCaseTimeline(caseId), caseId, { pollMs: POLL_MS });
  const decisionsFetch = useFetch(() => getCaseDecisions(caseId), caseId, { pollMs: POLL_MS });

  const rows = useMemo(
    () => buildTimelineRows(decisionsFetch.data ?? [], timelineFetch.data ?? []),
    [decisionsFetch.data, timelineFetch.data],
  );

  const isLoading = caseFetch.isLoading || timelineFetch.isLoading || decisionsFetch.isLoading;
  const error = caseFetch.error ?? timelineFetch.error ?? decisionsFetch.error;

  if (isLoading) {
    return (
      <div className="mx-auto max-w-300 px-8 py-8">
        <LoadingState rows={6} />
      </div>
    );
  }

  if (error || !caseFetch.data) {
    return (
      <div className="mx-auto max-w-300 px-8 py-8">
        <ErrorState message={error ?? "Case not found."} onRetry={caseFetch.refetch} />
      </div>
    );
  }

  const c = caseFetch.data;
  const description = firstInboundSummary(timelineFetch.data ?? []);

  return (
    <div>
      <CaseHeader caseSnapshot={c} description={description} />

      <div className="grid grid-cols-1 gap-6 px-8 py-6 coll:grid-cols-[minmax(0,1fr)_320px]">
        <section aria-label="Timeline">
          <CaseTimeline rows={rows} />
        </section>

        <aside
          aria-label="Case intelligence"
          className="h-fit rounded-md border border-border bg-surface coll:sticky coll:top-6"
        >
          <div className="border-b border-border px-4 py-3">
            <h2 className="text-[13px] font-semibold text-text-primary">Case</h2>
          </div>

          <Section title="Stakeholders">
            <StakeholderList
              requiredRoles={c.required_roles}
              missingRoles={c.missing_roles}
              participants={c.participants}
            />
          </Section>

          <Section title="Channels">
            {c.channels_used.length > 0 ? (
              <ul className="space-y-1 text-[13px] text-text-primary">
                {c.channels_used.map((channel) => (
                  <li key={channel}>{channelLabel(channel)}</li>
                ))}
              </ul>
            ) : (
              <p className="text-[13px] text-text-muted">No channel used yet.</p>
            )}
          </Section>

          <Section title="Priority">
            <CasePriority priority={c.priority} />
          </Section>

          <Section title="Communication health">
            <CaseHealth health={c.communication_health} />
          </Section>

          <Section title="Follow-up">
            <FollowUpStatus nextCheckAt={c.next_check_at} attemptCount={c.attempt_count} />
          </Section>

          <Section title="Resolution">
            <Badge tone={resolutionTone(c.resolution_status)}>
              {resolutionLabel(c.resolution_status)}
            </Badge>
          </Section>
        </aside>
      </div>
    </div>
  );
}
