import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Calendar as CalendarIcon, X } from "@phosphor-icons/react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";

/** Simple inline date range using native <input type="date"> to avoid heavy deps. */
export default function DateRangeFilter({ from, to, onChange, testId = "date-range" }) {
  const set = (k, v) => onChange({ from, to, [k]: v });
  const clear = () => onChange({ from: "", to: "" });
  const active = !!(from || to);

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button data-testid={testId}
                className={`h-9 px-3 rounded-full border flex items-center gap-2 text-xs font-mono uppercase tracking-wider transition-colors
                  ${active
                    ? "bg-[var(--primary-soft)] border-[var(--primary)] text-[var(--primary)]"
                    : "border-[var(--border)] text-[var(--fg-muted)] hover:bg-[var(--surface-hover)]"}`}>
          <CalendarIcon size={13} weight="bold" />
          {active ? `${from || "…"} → ${to || "…"}` : "Date range"}
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-72 bg-[var(--surface)] border-[var(--border)]">
        <div className="space-y-3">
          <div>
            <label className="text-[10px] uppercase tracking-wider text-[var(--fg-muted)]">From</label>
            <Input type="date" value={from || ""} onChange={(e) => set("from", e.target.value)}
                   className="bg-[var(--bg)] border-[var(--border)] rounded-md mt-1"
                   data-testid="date-from" />
          </div>
          <div>
            <label className="text-[10px] uppercase tracking-wider text-[var(--fg-muted)]">To</label>
            <Input type="date" value={to || ""} onChange={(e) => set("to", e.target.value)}
                   className="bg-[var(--bg)] border-[var(--border)] rounded-md mt-1"
                   data-testid="date-to" />
          </div>
          {active && (
            <Button variant="outline" onClick={clear}
                    className="w-full rounded-full gap-1 text-xs" data-testid="date-clear">
              <X size={12} /> Clear
            </Button>
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}
