"use client";

import { useEffect } from "react";
import { capture } from "@/lib/analytics";

export default function DisclosuresTracker() {
  useEffect(() => { capture("disclosures_viewed"); }, []);
  return null;
}
