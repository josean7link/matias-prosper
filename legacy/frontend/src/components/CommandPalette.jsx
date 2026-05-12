import { useEffect, useState, useRef, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import api from "@/lib/api";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { MagnifyingGlass, ArrowRight, Command } from "@phosphor-icons/react";

/** Global ⌘K command palette. */
export default function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [groups, setGroups] = useState([]);
  const [loading, setLoading] = useState(false);
  const [highlightIdx, setHighlightIdx] = useState(0);
  const inputRef = useRef(null);
  const navigate = useNavigate();

  // Global shortcut ⌘K / Ctrl+K
  useEffect(() => {
    const handler = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((o) => !o);
      }
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  // Search debounce
  useEffect(() => {
    if (!open) { setGroups([]); return; }
    if (!q) { setGroups([]); return; }
    const t = setTimeout(async () => {
      setLoading(true);
      try {
        const { data } = await api.get(`/search?q=${encodeURIComponent(q)}`);
        setGroups((data.groups || []).filter((g) => g.items.length > 0));
        setHighlightIdx(0);
      } catch {} finally { setLoading(false); }
    }, 180);
    return () => clearTimeout(t);
  }, [q, open]);

  // Flatten items for keyboard nav
  const flat = groups.flatMap((g) => g.items.map((it) => ({ ...it, kind: g.kind })));

  const goto = useCallback((item) => {
    setOpen(false); setQ(""); setGroups([]);
    if (item?.url) navigate(item.url);
  }, [navigate]);

  const onKey = (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setHighlightIdx((i) => Math.min(i + 1, flat.length - 1)); }
    if (e.key === "ArrowUp") { e.preventDefault(); setHighlightIdx((i) => Math.max(0, i - 1)); }
    if (e.key === "Enter" && flat[highlightIdx]) { e.preventDefault(); goto(flat[highlightIdx]); }
  };

  const quickActions = [
    { label: "Go to Dashboard", url: "/app", kind: "action" },
    { label: "Operations Queue", url: "/app/approvals", kind: "action" },
    { label: "Transactions Ledger", url: "/app/transactions", kind: "action" },
    { label: "Alerts Center", url: "/app/alerts", kind: "action" },
    { label: "Audit Log", url: "/app/audit", kind: "action" },
  ];
  const showQuick = !q;

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="max-w-2xl p-0 bg-[var(--surface)] border-[var(--border)] rounded-xl overflow-hidden"
                     data-testid="command-palette">
        <div className="flex items-center gap-3 px-4 py-3 border-b border-[var(--border)]">
          <MagnifyingGlass size={18} className="text-[var(--fg-muted)]" />
          <input
            ref={inputRef} autoFocus
            value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={onKey}
            placeholder="Search clients, transactions, positions, keys, cases…"
            className="flex-1 bg-transparent outline-none text-[var(--fg)] placeholder:text-[var(--fg-subtle)] text-sm"
            data-testid="cmdk-input"
          />
          <kbd className="font-mono text-[10px] px-2 py-0.5 rounded border border-[var(--border)] text-[var(--fg-muted)]">ESC</kbd>
        </div>

        <div className="max-h-[420px] overflow-y-auto">
          {showQuick && (
            <Group label="Quick actions">
              {quickActions.map((a, i) => (
                <Item key={a.label} item={a} onClick={() => goto(a)} testId={`cmdk-quick-${i}`} />
              ))}
            </Group>
          )}
          {loading && !showQuick && (
            <div className="px-4 py-8 text-center text-xs text-[var(--fg-muted)]">Searching…</div>
          )}
          {!loading && !showQuick && groups.length === 0 && (
            <div className="px-4 py-8 text-center text-xs text-[var(--fg-muted)]">No results for "{q}"</div>
          )}
          {groups.map((g) => (
            <Group key={g.kind} label={g.label}>
              {g.items.map((it) => {
                const flatIdx = flat.findIndex((x) => x.id === it.id && x.kind === g.kind);
                const highlighted = flatIdx === highlightIdx;
                return (
                  <Item key={it.id} item={it} highlighted={highlighted}
                        onClick={() => goto(it)}
                        testId={`cmdk-result-${it.id}`} />
                );
              })}
            </Group>
          ))}
        </div>

        <div className="px-4 py-2 border-t border-[var(--border)] flex items-center gap-3 text-[10px] text-[var(--fg-subtle)] font-mono">
          <span><Command size={10} className="inline" /> K to open</span>
          <span>↑↓ navigate</span>
          <span>↵ go</span>
        </div>
      </DialogContent>
    </Dialog>
  );
}

const Group = ({ label, children }) => (
  <div className="py-1">
    <div className="px-4 py-1.5 text-[10px] uppercase tracking-[0.15em] text-[var(--fg-subtle)] font-mono">{label}</div>
    {children}
  </div>
);

const Item = ({ item, highlighted, onClick, testId }) => (
  <button onClick={onClick} data-testid={testId}
          className={`w-full text-left px-4 py-2.5 flex items-center gap-3 transition-colors ${
            highlighted ? "bg-[var(--primary-soft)]" : "hover:bg-[var(--surface-hover)]"
          }`}>
    <div className="flex-1 min-w-0">
      <div className="text-sm text-[var(--fg)] truncate">{item.title || item.label}</div>
      {item.subtitle && <div className="text-xs text-[var(--fg-muted)] font-mono truncate">{item.subtitle}</div>}
    </div>
    <ArrowRight size={12} className="text-[var(--fg-subtle)]" weight="bold" />
  </button>
);
