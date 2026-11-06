import LegalPage from "@/components/legal/LegalPage";
import { PRIVACY_DRAFT } from "@/lib/legalDrafts";

export default function PrivacyPage() {
  return <LegalPage doc={PRIVACY_DRAFT} />;
}
