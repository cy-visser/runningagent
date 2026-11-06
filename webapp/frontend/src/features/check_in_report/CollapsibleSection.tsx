import { useId, useState } from "react";
import { ChevronDown } from "lucide-react";
import { sectionTeaser } from "../../shared/format";
import { RichMarkdown } from "../../shared/RichMarkdown";

interface CollapsibleSectionProps {
  title: string;
  body: string;
  defaultOpen?: boolean;
}

/**
 * Report section that starts collapsed: header + a one-line teaser box. Clicking the
 * header or the teaser expands the full markdown body; clicking the header collapses it.
 */
export function CollapsibleSection({ title, body, defaultOpen = false }: CollapsibleSectionProps) {
  const [open, setOpen] = useState(defaultOpen);
  const bodyId = useId();
  const teaser = sectionTeaser(body);

  return (
    <div className="rounded-xl border border-slate-200 bg-white">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={bodyId}
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left"
      >
        <h3 className="font-display text-base font-bold text-slate-900">{title}</h3>
        <ChevronDown
          className={`h-4 w-4 shrink-0 text-slate-500 transition-transform duration-200 ${open ? "rotate-180" : ""}`}
        />
      </button>

      {open ? (
        <div id={bodyId} className="border-t border-slate-100 px-4 py-3">
          <RichMarkdown content={body} />
        </div>
      ) : (
        <button
          type="button"
          id={bodyId}
          onClick={() => setOpen(true)}
          className="mx-4 mb-3 flex w-[calc(100%-2rem)] items-center gap-2 rounded-lg border border-slate-100 bg-slate-50/70 px-3 py-2 text-left text-sm text-slate-600 transition-colors hover:border-orange-200 hover:bg-orange-50/40"
        >
          <span className="min-w-0 flex-1 truncate">{teaser || "Details"}</span>
          <span className="shrink-0 font-semibold text-orange-600">Show more</span>
        </button>
      )}
    </div>
  );
}
