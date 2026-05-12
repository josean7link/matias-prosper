const TONES = {
  default: { bg: "rgb(var(--surface-hover))", fg: "rgb(var(--fg-muted))" },
  primary: { bg: "color-mix(in srgb, #2B6BFF 14%, transparent)", fg: "#2B6BFF" },
  success: { bg: "color-mix(in srgb, #0FA958 14%, transparent)", fg: "#0FA958" },
  warning: { bg: "color-mix(in srgb, #E07B00 14%, transparent)", fg: "#E07B00" },
  danger:  { bg: "color-mix(in srgb, #DC2626 14%, transparent)", fg: "#DC2626" },
};

type Tone = keyof typeof TONES;

// Map common status strings to tones.
const STATUS_TONE: Record<string, Tone> = {
  approved: "success", active: "success", success: "success", confirmed: "success",
  pending: "warning", kyb_pending: "warning", review: "warning", needs_info: "warning",
  rejected: "danger", failed: "danger", error: "danger", critical: "danger", revoked: "danger",
  submitted: "primary", processing: "primary", under_review: "primary", new: "primary",
};

export function Badge({
  children,
  tone,
  size = "md",
}: {
  children: React.ReactNode;
  tone?: Tone | "auto";
  size?: "sm" | "md";
}) {
  let pickedTone: Tone = "default";
  if (tone && tone !== "auto") pickedTone = tone;
  else if (tone === "auto" && typeof children === "string") {
    pickedTone = STATUS_TONE[children.toLowerCase()] || "default";
  }
  const c = TONES[pickedTone];
  const pad = size === "sm" ? "px-2 py-0.5 text-[10px]" : "px-2.5 py-1 text-xs";
  return (
    <span
      className={`inline-flex items-center font-mono uppercase tracking-wider rounded ${pad}`}
      style={{ background: c.bg, color: c.fg }}
      data-testid={`badge-${String(children).toLowerCase().replace(/[^a-z0-9]/g, "-")}`}
    >
      {children}
    </span>
  );
}
