import React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  extractLeadingStatus,
  parseAsciiProgressBar,
  splitReportPlaceholders,
  type StatusPillTone,
} from "../lib/format";

interface RichMarkdownProps {
  content: string;
}

const PILL_STYLES: Record<StatusPillTone, string> = {
  emerald: "bg-emerald-50 text-emerald-700 border-emerald-200",
  amber: "bg-amber-50 text-amber-800 border-amber-200",
  rose: "bg-rose-50 text-rose-700 border-rose-200",
  slate: "bg-slate-100 text-slate-700 border-slate-200",
};

const PILL_DOT: Record<StatusPillTone, string> = {
  emerald: "bg-emerald-500",
  amber: "bg-amber-500",
  rose: "bg-rose-500",
  slate: "bg-slate-400",
};

function flattenChildrenText(node: React.ReactNode): string {
  if (typeof node === "string" || typeof node === "number") {
    return String(node);
  }
  if (Array.isArray(node)) {
    return node.map(flattenChildrenText).join("");
  }
  if (React.isValidElement(node)) {
    const props = node.props as { children?: React.ReactNode };
    return flattenChildrenText(props.children);
  }
  return "";
}

export function StatusPill({
  tone,
  label,
}: {
  tone: StatusPillTone;
  label: string;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-semibold whitespace-nowrap ${PILL_STYLES[tone]}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${PILL_DOT[tone]}`} />
      <span>{label}</span>
    </span>
  );
}

export function SunsetProgressBar({ percent }: { percent: number }) {
  const clamped = Math.min(100, Math.max(0, percent));
  return (
    <span
      className="inline-flex items-center gap-2 align-middle"
      role="progressbar"
      aria-valuenow={clamped}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <span className="inline-block h-2 w-24 overflow-hidden rounded-full bg-slate-100 border border-slate-200/80">
        <span
          className="block h-full rounded-full bg-sunset transition-all duration-300"
          style={{ width: `${clamped}%` }}
        />
      </span>
    </span>
  );
}

export function RichMarkdown({ content }: RichMarkdownProps) {
  const segments = splitReportPlaceholders(content);

  return (
    <div className="space-y-3 text-sm leading-relaxed text-slate-700">
      {segments.map((seg, idx) => {
        if (seg.type === "placeholder") {
          return (
            <div
              key={`ph-${idx}`}
              className="rounded-2xl border border-orange-200/70 p-4 animate-shimmer"
            >
              <div className="h-3 w-44 rounded-full bg-orange-200/60 mb-2.5" />
              <div className="h-2.5 w-full rounded-full bg-slate-200/70 mb-2" />
              <div className="h-2.5 w-4/5 rounded-full bg-slate-200/70" />
            </div>
          );
        }

        return (
          <ReactMarkdown
            key={`md-${idx}`}
            remarkPlugins={[remarkGfm]}
            components={{
              h1: ({ children }) => (
                <h1 className="font-display text-lg font-bold text-slate-900 mt-4 mb-2 first:mt-0">
                  {children}
                </h1>
              ),
              h2: ({ children }) => (
                <h2 className="font-display text-base font-bold text-slate-900 mt-4 mb-2 first:mt-0">
                  {children}
                </h2>
              ),
              h3: ({ children }) => (
                <h3 className="font-display text-sm font-bold text-slate-900 mt-4 mb-1.5 first:mt-0">
                  {children}
                </h3>
              ),
              p: ({ children }) => (
                <p className="leading-relaxed text-slate-700 my-2 first:mt-0 last:mb-0">
                  {children}
                </p>
              ),
              ul: ({ children }) => (
                <ul className="my-2 list-disc space-y-1.5 pl-5 text-slate-700">
                  {children}
                </ul>
              ),
              ol: ({ children }) => (
                <ol className="my-2 list-decimal space-y-1.5 pl-5 text-slate-700">
                  {children}
                </ol>
              ),
              li: ({ children }) => (
                <li className="leading-relaxed">{children}</li>
              ),
              strong: ({ children }) => (
                <strong className="font-semibold text-slate-900">
                  {children}
                </strong>
              ),
              blockquote: ({ children }) => (
                <blockquote className="my-3 rounded-r-xl border-l-3 border-orange-400 bg-orange-50/50 py-2 px-3.5 text-xs text-slate-700">
                  {children}
                </blockquote>
              ),
              table: ({ children }) => (
                <div className="my-3 overflow-x-auto rounded-2xl border border-slate-200 bg-white shadow-2xs">
                  <table className="min-w-full divide-y divide-slate-200 text-left text-xs">
                    {children}
                  </table>
                </div>
              ),
              thead: ({ children }) => (
                <thead className="bg-slate-50 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                  {children}
                </thead>
              ),
              tbody: ({ children }) => (
                <tbody className="divide-y divide-slate-100 bg-white">
                  {children}
                </tbody>
              ),
              tr: ({ children }) => (
                <tr className="even:bg-slate-50/40 hover:bg-orange-50/30 transition-colors">
                  {children}
                </tr>
              ),
              th: ({ children }) => (
                <th className="px-3.5 py-2.5 font-semibold text-slate-600">
                  {children}
                </th>
              ),
              td: ({ children }) => {
                const rawText = flattenChildrenText(children).trim();
                const status = extractLeadingStatus(rawText);
                if (status) {
                  return (
                    <td className="px-3.5 py-2.5 align-middle text-slate-700 tabular-nums">
                      <span className="inline-flex flex-wrap items-center gap-1.5">
                        <StatusPill
                          tone={status.tone}
                          label={status.badgeText}
                        />
                        {status.restText && <span>{status.restText}</span>}
                      </span>
                    </td>
                  );
                }
                return (
                  <td className="px-3.5 py-2.5 align-middle text-slate-700 tabular-nums">
                    {children}
                  </td>
                );
              },
              code: ({ className, children }) => {
                const raw = flattenChildrenText(children);
                const isBlock = Boolean(className) || raw.includes("\n");
                if (!isBlock) {
                  const bar = parseAsciiProgressBar(raw);
                  if (bar) {
                    return <SunsetProgressBar percent={bar.percent} />;
                  }
                  return (
                    <code className="rounded-md border border-slate-200 bg-slate-50 px-1.5 py-0.5 font-mono text-xs text-slate-800">
                      {children}
                    </code>
                  );
                }
                return (
                  <pre className="my-2 overflow-x-auto rounded-xl border border-slate-200 bg-slate-900 p-3 font-mono text-xs text-slate-100">
                    <code>{children}</code>
                  </pre>
                );
              },
            }}
          >
            {seg.content}
          </ReactMarkdown>
        );
      })}
    </div>
  );
}
