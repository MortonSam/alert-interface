export default function Loading() {
  return (
    <main className="min-h-[80vh] flex items-center justify-center p-8">
      <div className="flex flex-col items-center gap-4">
        <div className="flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full bg-primary animate-pulse" />
          <span className="h-2 w-2 rounded-full bg-primary animate-pulse [animation-delay:150ms]" />
          <span className="h-2 w-2 rounded-full bg-primary animate-pulse [animation-delay:300ms]" />
        </div>
        <p className="font-mono text-xs text-muted-foreground">Loading</p>
      </div>
    </main>
  );
}
