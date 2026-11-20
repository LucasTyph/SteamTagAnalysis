import { describe, expect, it } from "vitest";
import { type Meta, dataAsOf } from "./meta";

const meta = (build: Record<string, unknown>): Meta => ({ build, analysis: {}, excluded_tags: [], counts: {} });

describe("dataAsOf", () => {
  it("names the month the data was fetched", () => {
    expect(dataAsOf(meta({ data_as_of: "2026-11-01" }))).toBe("November 2026");
    expect(dataAsOf(meta({ data_as_of: "2026-12-31" }))).toBe("December 2026");
  });

  it("is null without a date", () => {
    expect(dataAsOf(meta({}))).toBeNull();
    expect(dataAsOf(undefined)).toBeNull();
  });
});
