/** Which section tab is lit. A section is current once its top passes a line a third of the way down the space below the sticky
 *  tabs (measured, not assumed: on a phone the tabs wrap to two rows). At the bottom of the page the last section that has reached
 *  the screen is current, since the final section may be too short to scroll its top up to the line. */
export function activeSection(
  tops: { id: string; top: number }[],
  navBottom: number,
  viewportHeight: number,
  atBottom: boolean,
): string | null {
  if (!tops.length) return null;
  const line = navBottom + (viewportHeight - navBottom) / 3;
  let current = tops[0].id;
  for (const s of tops) if (s.top <= line) current = s.id;
  if (atBottom) {
    const onScreen = tops.filter((s) => s.top < viewportHeight);
    if (onScreen.length) current = onScreen[onScreen.length - 1].id;
  }
  return current;
}
