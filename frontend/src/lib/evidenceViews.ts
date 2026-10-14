// The Evidence section's two-way switch at the top: Reports (the tap-a-report cards) and Chart (the reaction chart, distribution,
// peers and the table). The first entry is the view the section opens on.
export type EvidenceView = "reports" | "chart";

export const EVIDENCE_VIEWS: { key: EvidenceView; label: string }[] = [
  { key: "reports", label: "Reports" },
  { key: "chart", label: "Chart" },
];
