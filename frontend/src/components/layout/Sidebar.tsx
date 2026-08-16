import { NavLink } from "react-router-dom";
import { Folder, Activity, LayoutGrid, Settings } from "lucide-react";
import { LogoMark, Wordmark } from "./Logo";
import { cx } from "../../lib/utils";

const NAV_ITEMS = [
  { to: "/cases", label: "Cases", icon: Folder },
  { to: "/activity", label: "Activity", icon: Activity },
  { to: "/overview", label: "Overview", icon: LayoutGrid },
] as const;

export function Sidebar() {
  return (
    <aside
      className="flex h-full w-16 shrink-0 flex-col border-r border-border bg-surface coll:w-56"
      aria-label="Primary"
    >
      <div className="flex h-14 items-center px-4">
        <span className="coll:hidden">
          <LogoMark />
        </span>
        <span className="hidden coll:block">
          <Wordmark />
        </span>
      </div>

      <nav className="flex flex-col gap-0.5 px-2 py-2">
        {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            title={label}
            className={({ isActive }) =>
              cx(
                "flex items-center justify-center gap-2.5 rounded-md px-2.5 py-1.5 text-[13px] font-medium transition-colors coll:justify-start",
                isActive
                  ? "bg-surface-secondary text-accent"
                  : "text-text-secondary hover:bg-surface-secondary hover:text-text-primary",
              )
            }
          >
            <Icon size={15} strokeWidth={1.75} />
            <span className="hidden coll:inline">{label}</span>
          </NavLink>
        ))}

        {/* Listed in the product IA but deliberately not built (spec §30: "Do not build a
           settings-heavy interface") — present as a disabled placeholder, not a dead promise. */}
        <div
          className="flex cursor-not-allowed items-center justify-center gap-2.5 rounded-md px-2.5 py-1.5 text-[13px] font-medium text-text-muted coll:justify-start"
          aria-disabled="true"
          title="Settings"
        >
          <Settings size={15} strokeWidth={1.75} />
          <span className="hidden coll:inline">Settings</span>
        </div>
      </nav>
    </aside>
  );
}
