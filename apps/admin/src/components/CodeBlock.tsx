"use client";
import { useState } from "react";
import { Copy, Check } from "lucide-react";

export function CodeBlock({ code, lang = "bash", testid }:
  { code: string; lang?: string; testid?: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    await navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <div className="relative group rounded-lg border border-border bg-bg overflow-hidden"
         data-testid={testid}>
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-border bg-surface">
        <span className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle">
          {lang}
        </span>
        <button onClick={copy}
          className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle hover:text-fg
                     inline-flex items-center gap-1"
          data-testid={testid ? `${testid}-copy` : "code-copy"}>
          {copied ? <><Check size={10}/> Copiado</> : <><Copy size={10}/> Copiar</>}
        </button>
      </div>
      <pre className="p-3 text-xs font-mono text-fg overflow-x-auto whitespace-pre">
        <code>{code}</code>
      </pre>
    </div>
  );
}

export function CodeTabs({ tabs, testid }:
  { tabs: { id: string; label: string; lang?: string; code: string }[];
    testid?: string }) {
  const [active, setActive] = useState(tabs[0]?.id);
  const current = tabs.find((t) => t.id === active);
  return (
    <div className="rounded-lg border border-border bg-bg overflow-hidden" data-testid={testid}>
      <div className="flex items-center border-b border-border bg-surface">
        <div className="flex">
          {tabs.map((t) => (
            <button key={t.id} onClick={() => setActive(t.id)}
              className={`px-3 py-1.5 text-[10px] font-mono uppercase tracking-wider
                          ${active === t.id
                            ? "text-fg border-b-2 border-primary -mb-px"
                            : "text-fg-subtle hover:text-fg"}`}
              data-testid={testid ? `${testid}-tab-${t.id}` : `tab-${t.id}`}>
              {t.label}
            </button>
          ))}
        </div>
        {current && (
          <CopyChip code={current.code}
                    testid={testid ? `${testid}-copy` : undefined} />
        )}
      </div>
      {current && (
        <pre className="p-3 text-xs font-mono text-fg overflow-x-auto whitespace-pre">
          <code>{current.code}</code>
        </pre>
      )}
    </div>
  );
}

function CopyChip({ code, testid }: { code: string; testid?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      onClick={async () => {
        await navigator.clipboard.writeText(code);
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      }}
      className="ml-auto px-3 py-1.5 text-[10px] font-mono uppercase tracking-wider
                 text-fg-subtle hover:text-fg inline-flex items-center gap-1"
      data-testid={testid}>
      {copied ? <><Check size={10}/> Copiado</> : <><Copy size={10}/> Copiar</>}
    </button>
  );
}
