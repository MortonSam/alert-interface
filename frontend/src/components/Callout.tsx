import { Info, AlertTriangle } from "lucide-react";
import { cn } from "@/lib/utils";

const tiers = {
  info: {
    text: "text-[#BFDBFF]",
    bg: "bg-[rgba(46,155,255,0.07)]",
    border: "border-[rgba(46,155,255,0.28)]",
    icon: "text-[#2E9BFF]",
    title: "text-[#9CCAFF]",
  },
  caution: {
    text: "text-[#FBD89B]",
    bg: "bg-[rgba(245,165,36,0.08)]",
    border: "border-[rgba(245,165,36,0.32)]",
    icon: "text-[#F5A524]",
    title: "text-[#FAC56A]",
  },
  alert: {
    text: "text-[#FFC2C2]",
    bg: "bg-[rgba(255,92,92,0.08)]",
    border: "border-[rgba(255,92,92,0.34)]",
    icon: "text-[#FF5C5C]",
    title: "text-[#FF9B9B]",
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
