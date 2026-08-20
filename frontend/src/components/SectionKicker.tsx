export function SectionKicker({ index, label }: { index: string; label: string }) {
  return (
    <p className="flex items-center gap-2 mb-4">
      <span className="font-mono text-xs text-muted-foreground/50">{index}</span>
      <span className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
        {label}
      </span>
    </p>
  );
}
