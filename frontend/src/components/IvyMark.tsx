import { BRAND } from "@/lib/brand";

/** Ivy's mark, small, beside her name. Decorative: the name beside it is the text. */
export function IvyMark({ size = 14, className = "" }: { size?: number; className?: string }) {
  // eslint-disable-next-line @next/next/no-img-element
  return <img src={BRAND.ivyMark} alt="" aria-hidden="true" width={size} height={size} className={`inline-block align-[-0.15em] rounded-[3px] ${className}`} />;
}
