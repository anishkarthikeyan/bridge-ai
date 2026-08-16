/** The Bridge AI mark — two points connected by a line: the core "one case, many people,
 * one continuous thread" idea, kept as understated as possible (spec §28: no AI-brain
 * iconography). */
export function LogoMark({ size = 16 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 20 20"
      fill="none"
      aria-hidden="true"
      className="shrink-0"
    >
      <circle cx="4" cy="10" r="2.5" fill="var(--color-accent)" />
      <circle cx="16" cy="10" r="2.5" fill="var(--color-accent)" />
      <line x1="6.5" y1="10" x2="13.5" y2="10" stroke="var(--color-accent)" strokeWidth="1.5" />
    </svg>
  );
}

export function Wordmark({ withSubtitle = false }: { withSubtitle?: boolean }) {
  return (
    <div className="flex items-center gap-2">
      <LogoMark />
      <div className="leading-tight">
        <div className="text-[13px] font-semibold tracking-wide text-text-primary">BRIDGE AI</div>
        {withSubtitle ? (
          <div className="text-[11px] text-text-muted">Autonomous Communication Agent</div>
        ) : null}
      </div>
    </div>
  );
}
