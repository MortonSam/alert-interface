import { permanentRedirect } from "next/navigation";

// Ivy's Desk, Ivy's Trades and their old addresses are gone (Sam, 2026-11-02); every old URL lands on the one Ivy page.
export default function Moved() {
  permanentRedirect("/ivy");
}
