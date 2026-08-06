export default function Logo({ size = 24, className = "", wordmark = true, testId = "prosper-logo" }) {
  return (
    <div className={`inline-flex items-center gap-2 ${className}`} data-testid={testId}>
      <svg width={size} height={size} viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg">
        {/* Prosper 4-petal mark */}
        <path
          d="M20 4 C 24 10, 30 10, 36 14 C 30 18, 30 22, 36 26 C 30 30, 24 30, 20 36 C 16 30, 10 30, 4 26 C 10 22, 10 18, 4 14 C 10 10, 16 10, 20 4 Z"
          fill="none"
          stroke="#0066FF"
          strokeWidth="2.5"
          strokeLinejoin="round"
        />
        <circle cx="20" cy="20" r="3" fill="#0066FF" />
      </svg>
      {wordmark && (
        <span
          className="font-display font-black tracking-tight text-[var(--brand-fg)]"
          style={{ fontSize: size * 0.9 }}
        >
          prosper
        </span>
      )}
    </div>
  );
}
