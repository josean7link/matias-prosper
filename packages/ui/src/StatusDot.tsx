const COLORS = {
  green:  "#0FA958",
  yellow: "#E07B00",
  red:    "#DC2626",
  grey:   "#5B6478",
};

export type DotColor = keyof typeof COLORS;

export function StatusDot({
  color = "grey",
  pulse = false,
  label,
}: {
  color?: DotColor;
  pulse?: boolean;
  label?: string;
}) {
  const c = COLORS[color];
  return (
    <span className="inline-flex items-center gap-2" data-testid={`status-dot-${color}`}>
      <span className="relative inline-flex w-2 h-2">
        {pulse && (
          <span
            className="absolute inline-flex w-full h-full rounded-full opacity-60 animate-ping"
            style={{ background: c }}
          />
        )}
        <span
          className="relative inline-flex w-2 h-2 rounded-full"
          style={{ background: c }}
        />
      </span>
      {label && (
        <span className="text-xs text-fg-muted font-mono uppercase tracking-wider">
          {label}
        </span>
      )}
    </span>
  );
}
