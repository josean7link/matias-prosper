import { cn } from "@/lib/utils";

export function ProsperLogo({ className }: { className?: string }) {
  return (
    <div className={cn("flex items-center gap-2 select-none", className)}>
      <div className="w-7 h-7 rounded bg-primary flex items-center justify-center">
        <span className="font-display font-black text-white text-base leading-none">P</span>
      </div>
      <span className="font-display font-extrabold text-fg tracking-tight text-lg">
        Prosper
      </span>
    </div>
  );
}
