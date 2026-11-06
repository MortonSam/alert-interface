import LegalPage from "@/components/legal/LegalPage";
import { TERMS_DRAFT } from "@/lib/legalDrafts";

export default function TermsPage() {
  return <LegalPage doc={TERMS_DRAFT} />;
}
