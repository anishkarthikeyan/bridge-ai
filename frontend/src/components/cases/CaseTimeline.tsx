import { useEffect, useRef, useState } from "react";
import type { TimelineRow } from "../../lib/timelineRows";
import { TimelineEvent } from "./TimelineEvent";
import { EmptyState } from "../common/EmptyState";
import { Activity } from "lucide-react";

interface CaseTimelineProps {
  rows: TimelineRow[];
}

/** Thin vertical line, small node markers — the timeline is the centerpiece (spec §9). New
 * rows fade/slide in once (on the poll tick that first surfaces them), not on every
 * re-render — see the seenKeys bookkeeping below. */
export function CaseTimeline({ rows }: CaseTimelineProps) {
  const seenKeys = useRef<Set<string>>(new Set());
  const [, forceRenderTick] = useState(0);

  useEffect(() => {
    const unseen = rows.some((r) => !seenKeys.current.has(r.key));
    if (unseen) {
      // Paint this tick with the old seen-set (so new rows animate), then adopt the new set.
      const id = requestAnimationFrame(() => {
        seenKeys.current = new Set(rows.map((r) => r.key));
        forceRenderTick((t) => t + 1);
      });
      return () => cancelAnimationFrame(id);
    }
  }, [rows]);

  if (rows.length === 0) {
    return (
      <EmptyState
        icon={Activity}
        title="No activity yet"
        description="Bridge AI hasn't processed any messages on this case yet."
      />
    );
  }

  return (
    <div className="space-y-3">
      {rows.map((row) => (
        <TimelineEvent key={row.key} row={row} isNew={!seenKeys.current.has(row.key)} />
      ))}
    </div>
  );
}
