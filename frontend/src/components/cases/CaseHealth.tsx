import type { CommunicationHealth } from "../../lib/types";
import { healthLabel, healthMeterValue, healthTone } from "../../lib/utils";
import { Badge } from "../common/Badge";

const METER_FILL: Record<string, string> = {
  neutral: "bg-text-muted",
  success: "bg-success",
  warning: "bg-warning",
  danger: "bg-danger",
  info: "bg-info",
  accent: "bg-accent",
};

/** A simple horizontal meter — explicitly not a circular gauge (spec §12). */
export function CaseHealth({ health }: { health: CommunicationHealth }) {
  const tone = healthTone(health);
  const value = healthMeterValue(health);
  return (
    <div>
      <div className="flex items-center justify-between">
        <Badge tone={tone}>{healthLabel(health)}</Badge>
        <span className="text-[12px] text-text-muted">{value}/100</span>
      </div>
      <div
        className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-surface-secondary"
        role="progressbar"
        aria-valuenow={value}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label="Communication health"
      >
        <div className={`h-full rounded-full ${METER_FILL[tone]}`} style={{ width: `${value}%` }} />
      </div>
    </div>
  );
}
