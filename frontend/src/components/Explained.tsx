"use client";

// A sentence with every glossary term in it explained on hover (lib/glossaryTerms TERMS, through ExplainTip). Used wherever a
// sentence from the API or a copy helper renders, so a term reaches a visitor only with its plain-English explanation.
import { Fragment } from "react";
import ExplainTip from "@/components/ticker/ExplainTip";
import { explainSegments } from "@/lib/explainSegments";

export default function Explained({ text }: { text: string | null | undefined }) {
  if (!text) return null;
  return (
    <>
      {explainSegments(text).map((seg, i) =>
        seg.key ? <ExplainTip key={i} term={seg.key}>{seg.text}</ExplainTip> : <Fragment key={i}>{seg.text}</Fragment>)}
    </>
  );
}
