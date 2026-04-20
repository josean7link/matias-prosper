import { CaretLeft, CaretRight } from "@phosphor-icons/react";

export default function Pagination({ page, pageSize, total, onPageChange, testId = "pagination" }) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const canPrev = page > 1;
  const canNext = page < totalPages;
  const start = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const end = Math.min(page * pageSize, total);

  return (
    <div className="flex items-center justify-between px-4 py-3 border-t border-[var(--border)] text-xs"
         data-testid={testId}>
      <div className="text-[var(--fg-muted)] font-mono">
        {start.toLocaleString()}–{end.toLocaleString()} of {total.toLocaleString()}
      </div>
      <div className="flex items-center gap-2">
        <button onClick={() => canPrev && onPageChange(page - 1)}
                disabled={!canPrev}
                data-testid="page-prev"
                className="w-8 h-8 rounded-full border border-[var(--border)] hover:bg-[var(--surface-hover)] disabled:opacity-40 disabled:cursor-not-allowed flex items-center justify-center transition-colors">
          <CaretLeft size={12} weight="bold" />
        </button>
        <span className="font-mono">{page} / {totalPages}</span>
        <button onClick={() => canNext && onPageChange(page + 1)}
                disabled={!canNext}
                data-testid="page-next"
                className="w-8 h-8 rounded-full border border-[var(--border)] hover:bg-[var(--surface-hover)] disabled:opacity-40 disabled:cursor-not-allowed flex items-center justify-center transition-colors">
          <CaretRight size={12} weight="bold" />
        </button>
      </div>
    </div>
  );
}
