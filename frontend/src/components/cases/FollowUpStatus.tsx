import { formatDateTime, formatRelative } from "../../lib/utils";

interface FollowUpStatusProps {
  nextCheckAt: string | null;
  attemptCount: number;
}

export function FollowUpStatus({ nextCheckAt, attemptCount }: FollowUpStatusProps) {
  return (
    <dl className="space-y-1.5 text-[13px]">
      <div className="flex items-center justify-between">
        <dt className="text-text-secondary">Next check</dt>
        <dd className="text-text-primary" title={formatDateTime(nextCheckAt)}>
          {nextCheckAt ? formatRelative(nextCheckAt) : "Not scheduled"}
        </dd>
      </div>
      <div className="flex items-center justify-between">
        <dt className="text-text-secondary">Attempt</dt>
        <dd className="text-text-primary">{attemptCount}</dd>
      </div>
    </dl>
  );
}
