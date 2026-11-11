"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { useIvyMode } from "@/lib/useIvyMode";

/** The Desk and the Trades show only while the old Ivy does (lib/useIvyMode); with the walkthrough on they send the visitor to /ivy. */
export default function OldIvyOnly({ children }: { children: React.ReactNode }) {
  const ivy = useIvyMode();
  const router = useRouter();
  useEffect(() => {
    if (ivy.mode === "walkthrough") router.replace("/ivy");
  }, [ivy.mode, router]);
  return ivy.mode === "old" ? <>{children}</> : null;
}
