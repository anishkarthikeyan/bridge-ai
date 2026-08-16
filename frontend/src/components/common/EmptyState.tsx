import type { LucideIcon } from "lucide-react";
import { Inbox } from "lucide-react";

interface EmptyStateProps {
  icon?: LucideIcon;
  title: string;
  description?: string;
}

export function EmptyState({ icon: Icon = Inbox, title, description }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-md border border-border bg-surface px-6 py-16 text-center">
      <Icon size={20} className="text-text-muted" strokeWidth={1.5} />
      <p className="text-[14px] font-medium text-text-primary">{title}</p>
      {description ? <p className="max-w-sm text-[13px] text-text-secondary">{description}</p> : null}
    </div>
  );
}
