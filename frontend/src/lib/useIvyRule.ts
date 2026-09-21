"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { IvyRuleResponse } from "@/lib/ivyRule";

/** Ivy's rule and latest stored backtest. null until loaded, or if the request failed. */
export function useIvyRule(): IvyRuleResponse | null {
  const [data, setData] = useState<IvyRuleResponse | null>(null);
  useEffect(() => {
    let alive = true;
    api.theses.ivyRule().then((d) => { if (alive) setData(d); }).catch(() => {});
    return () => { alive = false; };
  }, []);
  return data;
}
