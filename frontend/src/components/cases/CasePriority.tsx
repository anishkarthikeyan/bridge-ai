import type { Priority } from "../../lib/types";
import { priorityLabel, priorityTone } from "../../lib/utils";
import { Badge } from "../common/Badge";

export function CasePriority({ priority }: { priority: Priority }) {
  return <Badge tone={priorityTone(priority)}>{priorityLabel(priority)}</Badge>;
}
