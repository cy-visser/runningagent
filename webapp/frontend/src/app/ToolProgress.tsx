import { CheckCircle2, Loader2, Sparkles } from "lucide-react";
import type { ToolChip } from "../shared/types";

interface ToolProgressProps {
  thinking?: boolean;
  tools?: ToolChip[];
}

export function ToolProgress({ thinking, tools }: ToolProgressProps) {
  const hasTools = Boolean(tools && tools.length > 0);
  if (!thinking && !hasTools) return null;

  return (
    <div className="mb-3 flex flex-wrap items-center gap-2">
      {thinking && !hasTools && (
        <span className="inline-flex items-center gap-1.5 rounded-full border border-orange-200 bg-orange-50/70 px-3 py-1 text-xs font-medium text-orange-800">
          <Sparkles className="h-3.5 w-3.5 text-orange-500 animate-pulse" />
          <span>Coach is reasoning…</span>
        </span>
      )}

      {tools?.map((chip) => {
        const running = chip.state === "start";
        return (
          <span
            key={chip.name}
            className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition ${
              running
                ? "border-orange-200 bg-orange-50 text-orange-800"
                : "border-slate-200 bg-slate-50 text-slate-600"
            }`}
          >
            {running ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin text-orange-500" />
            ) : (
              <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" />
            )}
            <span>{chip.label}</span>
          </span>
        );
      })}
    </div>
  );
}
