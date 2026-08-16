import { Link } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import type { CaseSnapshot } from "../../lib/types";
import {
  caseShortId,
  channelLabel,
  formatDateTime,
  healthLabel,
  healthTone,
  humanizeTopic,
  priorityLabel,
  priorityTone,
  resolutionLabel,
  resolutionTone,
} from "../../lib/utils";
import { Badge } from "../common/Badge";

interface CaseHeaderProps {
  caseSnapshot: CaseSnapshot;
  description: string | null;
}

export function CaseHeader({ caseSnapshot: c, description }: CaseHeaderProps) {
  const currentChannel = c.channels_used[c.channels_used.length - 1] ?? null;

  return (
    <header className="border-b border-border px-8 py-5">
      <Link
        to="/cases"
        className="inline-flex items-center gap-1 text-[13px] text-text-secondary hover:text-text-primary"
      >
        <ArrowLeft size={14} />
        Cases
      </Link>

      <div className="mt-2 flex items-start justify-between gap-4">
        <h1 className="text-[20px] font-semibold text-text-primary">{humanizeTopic(c.topic)}</h1>
        <div className="flex shrink-0 items-center gap-1.5">
          <Badge tone={priorityTone(c.priority)}>{priorityLabel(c.priority)}</Badge>
          <Badge tone={resolutionTone(c.resolution_status)}>{resolutionLabel(c.resolution_status)}</Badge>
        </div>
      </div>

      {description ? <p className="mt-1 text-[13px] text-text-secondary">{description}</p> : null}

      <dl className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1 text-[12px] text-text-muted">
        <div className="flex items-center gap-1">
          <dt>Case ID</dt>
          <dd className="font-mono text-text-secondary">CASE-{caseShortId(c.id)}</dd>
        </div>
        <div className="flex items-center gap-1">
          <dt>Created</dt>
          <dd className="text-text-secondary">{formatDateTime(c.created_at)}</dd>
        </div>
        <div className="flex items-center gap-1">
          <dt>Current channel</dt>
          <dd className="text-text-secondary">{currentChannel ? channelLabel(currentChannel) : "—"}</dd>
        </div>
        <div className="flex items-center gap-1">
          <dt>Health</dt>
          <dd>
            <Badge tone={healthTone(c.communication_health)}>{healthLabel(c.communication_health)}</Badge>
          </dd>
        </div>
      </dl>
    </header>
  );
}
