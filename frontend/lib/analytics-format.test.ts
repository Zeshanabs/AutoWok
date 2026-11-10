import { describe, expect, it } from "vitest";

import { availabilityText, filterQuery, formatChange, formatNumber, niceTicks, presetRange } from "@/lib/analytics-format";

describe("analytics formatting", () => {
  it("never renders a missing value as zero", () => {
    expect(formatNumber(null)).toBe("Not available");
    expect(formatNumber(undefined)).toBe("Not available");
    expect(formatNumber(0)).toBe("0");
    expect(formatNumber(1284)).toBe("1,284");
    expect(formatNumber(12900)).toBe("12.9K");
    expect(formatNumber(4_200_000)).toBe("4.2M");
    expect(formatNumber(12.5, "percent")).toBe("12.5%");
    expect(formatNumber(5400, "milliseconds")).toBe("5.4s");
  });

  it("formats percentage change and guards missing comparisons", () => {
    expect(formatChange(12.345)).toEqual({ text: "+12.3%", direction: "up" });
    expect(formatChange(-4)).toEqual({ text: "-4%", direction: "down" });
    expect(formatChange(0)).toEqual({ text: "0%", direction: "flat" });
    expect(formatChange(null)).toEqual({ text: "No comparison", direction: "none" });
  });

  it("explains availability notes in plain words", () => {
    expect(availabilityText("missing_permission:read_insights")).toContain("read_insights");
    expect(availabilityText("not_supported_on_platform")).toBe("Not reported by this platform");
    expect(availabilityText("insufficient_data")).toContain("minimum audience");
    expect(availabilityText(null)).toBe("Not available");
  });

  it("builds query strings and date presets", () => {
    const range = presetRange(7, "2026-11-10");
    expect(range).toEqual({ start: "2026-11-04", end: "2026-11-10" });
    const query = filterQuery({ ...range, preset: "7", brandId: "b1", platform: "instagram", accountId: "" }, { metric: "reach", limit: 10, source: "" });
    expect(query).toBe("start=2026-11-04&end=2026-11-10&brand_id=b1&platform=instagram&metric=reach&limit=10");
  });

  it("produces clean axis ticks", () => {
    expect(niceTicks(0)).toEqual([0, 1]);
    expect(niceTicks(830)).toEqual([0, 200, 400, 600, 800, 1000]);
    expect(niceTicks(3.2)).toEqual([0, 1, 2, 3, 4]);
  });
});
