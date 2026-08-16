import { AlertTriangle } from "lucide-react";

interface ErrorStateProps {
  message: string;
  onRetry?: () => void;
}

/** Never a raw stack trace — `message` is always the ApiError's own plain-sentence message
 * (see lib/api.ts's `request()`), not console output (spec §19). */
export function ErrorState({ message, onRetry }: ErrorStateProps) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-md border border-border bg-surface px-6 py-16 text-center">
      <AlertTriangle size={20} className="text-danger" strokeWidth={1.5} />
      <p className="text-[14px] font-medium text-text-primary">Unable to load data</p>
      <p className="max-w-sm text-[13px] text-text-secondary">{message}</p>
      {onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className="mt-1 rounded-md border border-border-strong bg-surface px-3 py-1.5 text-[13px] font-medium text-text-primary transition-colors hover:bg-surface-secondary"
        >
          Retry
        </button>
      ) : null}
    </div>
  );
}
