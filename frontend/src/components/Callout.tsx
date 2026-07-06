import { Info, AlertTriangle } from "lucide-react";
import { cn } from "@/lib/utils";

const tiers = {
  info: {
    text: "text-cool/75",
    bg: "bg-cool/[0.07]",
    border: "border-cool/[0.28]",
    icon: "text-cool",
    title: "text-cool/90",
  },
  caution: {
    text: "text-amber-500/75",
    bg: "bg-amber-500/[0.08]",
    border: "border-amber-500/[0.32]",
    icon: "text-amber-500",
    title: "text-amber-500/90",
  },
  alert: {
    text: "text-destructive/75",
    bg: "bg-destructive/[0.08]",
    border: "border-destructive/[0.34]",
    icon: "text-destructive",
    title: "text-destructive/90",
  },
};

interface CalloutProps {
  severity: "info" | "caution" | "alert";
  title?: string;
  children: React.ReactNode;
  className?: string;
  compact?: boolean;
  banner?: boolean;
}

export default function Callout({
  severity,
  title,
  children,
  className,
  compact,
  banner,
}: CalloutProps) {
  const t = tiers[severity];
  const Icon = severity === "info" ? Info : AlertTriangle;

  return (
    <div
      className={cn(
        "flex items-start",
        t.text,
        t.bg,
        banner
          ? cn("gap-3 border-b px-6 py-3 text-sm", t.border)
          : cn(
              "gap-2.5 rounded-[10px] border",
              t.border,
              compact
                ? "px-3 py-2 text-xs"
                : "px-3.5 py-3 text-[13px] leading-relaxed",
            ),
        className,
      )}
    >
      <Icon
        className={cn(
          "shrink-0 mt-0.5",
          t.icon,
          compact ? "w-3.5 h-3.5" : "w-4 h-4",
        )}
      />
      <div>
        {title && (
          <p className={cn("font-semibold text-[12.5px] mb-0.5", t.title)}>
            {title}
          </p>
        )}
        <div>{children}</div>
      </div>
    </div>
  );
}
