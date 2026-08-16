import { Check, AlertCircle } from "lucide-react";
import type { ParticipantSnapshot } from "../../lib/types";

interface StakeholderListProps {
  requiredRoles: string[];
  missingRoles: string[];
  participants: ParticipantSnapshot[];
}

/** Present/missing is never color-only — icon shape and label text both change too
 * (spec §24: "no color-only status indication"). */
export function StakeholderList({ requiredRoles, missingRoles, participants }: StakeholderListProps) {
  if (requiredRoles.length === 0) {
    return <p className="text-[13px] text-text-muted">No specific roles required for this topic.</p>;
  }

  const missing = new Set(missingRoles);

  return (
    <ul className="space-y-1.5">
      {requiredRoles.map((role) => {
        const isMissing = missing.has(role);
        const holder = participants.find((p) => p.role === role);
        return (
          <li key={role} className="flex items-center justify-between gap-2 text-[13px]">
            <span className="flex items-center gap-2 text-text-primary">
              {isMissing ? (
                <AlertCircle size={14} className="text-warning" strokeWidth={2} />
              ) : (
                <Check size={14} className="text-success" strokeWidth={2.25} />
              )}
              {role}
            </span>
            <span className="text-[12px] text-text-muted">
              {isMissing ? "Missing" : holder?.name ?? "Present"}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
