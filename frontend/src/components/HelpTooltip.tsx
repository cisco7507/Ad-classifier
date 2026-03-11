import type { ReactNode } from "react";
import { InfoCircledIcon } from "@radix-ui/react-icons";

type HelpTooltipProps = {
  content: ReactNode;
  label?: string;
  widthClassName?: string;
  align?: "center" | "start" | "end";
};

export function HelpTooltip({
  content,
  label = "Show help",
  widthClassName = "w-64",
  align = "center",
}: HelpTooltipProps) {
  const alignmentClassName =
    align === "start"
      ? "left-0 translate-x-0"
      : align === "end"
        ? "right-0 translate-x-0"
        : "left-1/2 -translate-x-1/2";

  return (
    <span className="relative inline-flex items-center align-middle group">
      <button
        type="button"
        aria-label={label}
        className="inline-flex h-4 w-4 items-center justify-center rounded-full border border-primary-200 bg-white text-primary-500 transition-colors hover:border-primary-400 hover:bg-primary-50 hover:text-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-300/60"
      >
        <InfoCircledIcon className="w-3 h-3" />
      </button>
      <span
        className={`pointer-events-none absolute top-full z-30 mt-2 rounded-2xl border border-primary-700/30 bg-primary-900 px-3 py-2 text-[11px] font-medium leading-relaxed text-white shadow-[0_20px_45px_rgba(0,31,68,0.30)] opacity-0 transition-opacity duration-150 group-hover:opacity-100 group-focus-within:opacity-100 ${alignmentClassName} ${widthClassName}`}
      >
        {content}
      </span>
    </span>
  );
}
