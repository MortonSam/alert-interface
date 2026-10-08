import type { Metadata } from "next";
import PreviewToken from "./PreviewToken";

// Lets the owner see flagged sections (Discover news) on a phone: the admin token is pasted here and kept only in this browser's
// localStorage, the same place the site already reads it from. The page carries no token and is not indexed.
export const metadata: Metadata = { title: "Preview", robots: { index: false, follow: false } };

export default function PreviewPage() {
  return (
    <main className="max-w-md mx-auto px-4 py-12">
      <PreviewToken />
    </main>
  );
}
