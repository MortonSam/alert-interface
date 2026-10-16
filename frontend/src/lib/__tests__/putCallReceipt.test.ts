import { describe, expect, it } from "vitest";
import { expirationList, putCallReceipt } from "@/lib/putCallReceipt";

describe("the put/call receipt names the expirations it sums", () => {
  it("lists each year's dates, then the year", () => {
    expect(expirationList(["2026-10-23", "2026-10-16", "2026-11-20"])).toBe("Oct 16, Oct 23 and Nov 20, 2026");
    expect(expirationList(["2026-12-18", "2027-01-15"])).toBe("Dec 18, 2026 and Jan 15, 2027");
    expect(expirationList(["2026-10-16"])).toBe("Oct 16, 2026");
  });
  it("reads a version-4 row by its list and a version-3 row as before", () => {
    expect(putCallReceipt({ expiration_used: "2026-10-16", expirations_used: ["2026-10-16", "2026-10-23", "2026-11-20"], snapshot_date: "2026-10-14" }))
      .toBe("volume across the Oct 16, Oct 23 and Nov 20, 2026 expirations, as of Oct 14, 2026");
    expect(putCallReceipt({ expiration_used: "2026-10-16", expirations_used: ["2026-10-16"], snapshot_date: "2026-10-14" }))
      .toBe("volume, the Oct 16, 2026 expiration, as of Oct 14, 2026");
    expect(putCallReceipt({ expiration_used: "2026-10-16", snapshot_date: "2026-10-14" })).toBe("volume, exp Oct 16, 2026, as of Oct 14, 2026");
    expect(putCallReceipt({ expiration_used: null, expirations_used: null, snapshot_date: null })).toBeNull();
  });
});
