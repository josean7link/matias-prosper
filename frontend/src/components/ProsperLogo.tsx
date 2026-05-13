import { cn } from "@/lib/utils";

interface Props {
  className?: string;
  /** Size variant of the wordmark. Default = sm. */
  size?: "sm" | "md" | "lg" | "xl";
  /** Render only the icon mark, no text. */
  iconOnly?: boolean;
  /** Force the icon + text color (otherwise inherits from parent). */
  monochrome?: "auto" | "white" | "ink" | "primary";
}

/**
 * Prosper brand mark — 4-leaf clover (trébol = prosperidad + conexión +
 * continuidad) + lowercase "prosper" wordmark. Color modes:
 *   - auto      (default): mark stays brand-primary; text inherits theme fg
 *   - white     : both mark and text white (for dark backgrounds / PDF)
 *   - ink       : both mark and text in #0B0F19 (light backgrounds)
 *   - primary   : both mark and text in #2563FF (color-block bg)
 */
export function ProsperLogo({ className, size = "sm",
                              iconOnly = false, monochrome = "auto" }: Props) {
  const wordCls = {
    sm: "text-lg",
    md: "text-2xl",
    lg: "text-3xl",
    xl: "text-5xl",
  }[size];
  const iconSize = { sm: 24, md: 30, lg: 38, xl: 56 }[size];

  const markCls = {
    auto:    "text-primary",
    white:   "text-white",
    ink:     "text-dark",
    primary: "text-primary",
  }[monochrome];
  const textCls = {
    auto:    "text-fg",
    white:   "text-white",
    ink:     "text-dark",
    primary: "text-primary",
  }[monochrome];

  return (
    <div className={cn("inline-flex items-center gap-2 select-none", className)}
         data-testid="prosper-logo">
      <CloverMark size={iconSize} className={markCls} />
      {!iconOnly && (
        <span className={cn(
          "font-display font-extrabold tracking-tight leading-none lowercase",
          wordCls, textCls,
        )}>
          prosper
        </span>
      )}
    </div>
  );
}

/**
 * 4-leaf clover SVG — two interlocking infinities (horizontal + vertical),
 * stroke-only, rounded line-caps. Inherits `color` via currentColor so the
 * parent class controls the brand color.
 */
export function CloverMark({ size = 24, className,
                             strokeWidth = 2.2 }:
  { size?: number; className?: string; strokeWidth?: number }) {
  return (
    <svg
      width={size} height={size}
      viewBox="0 0 32 32" fill="none" aria-hidden
      stroke="currentColor" strokeWidth={strokeWidth}
      strokeLinecap="round" strokeLinejoin="round"
      className={className}
      data-testid="prosper-clover"
    >
      {/* Top petal */}
      <ellipse cx="16" cy="10" rx="4.2" ry="7" />
      {/* Bottom petal */}
      <ellipse cx="16" cy="22" rx="4.2" ry="7" />
      {/* Left petal */}
      <ellipse cx="10" cy="16" rx="7" ry="4.2" />
      {/* Right petal */}
      <ellipse cx="22" cy="16" rx="7" ry="4.2" />
    </svg>
  );
}
