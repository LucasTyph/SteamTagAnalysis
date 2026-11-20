import { describe, expect, it } from "vitest";
import { ci90, tCritical90 } from "./stats";

describe("tCritical90", () => {
  it("matches t tables and approaches the normal value", () => {
    expect(tCritical90(1)).toBeCloseTo(6.314, 3);
    expect(tCritical90(10)).toBeCloseTo(1.812, 3);
    expect(tCritical90(30)).toBeCloseTo(1.697, 3);
    // scipy: t.ppf(0.95, 60) = 1.6706, t.ppf(0.95, 1000) = 1.6464
    expect(tCritical90(60)).toBeCloseTo(1.6706, 2);
    expect(tCritical90(1000)).toBeCloseTo(1.6464, 2);
    expect(tCritical90(0)).toBeNaN();
  });
});

describe("ci90", () => {
  it("is symmetric around the mean and shrinks with n", () => {
    const small = ci90(5, 10, 5)!;
    const big = ci90(5, 10, 100)!;
    expect(small.low + small.high).toBeCloseTo(10);
    expect(big.high - big.low).toBeLessThan(small.high - small.low);
    // half-width = t(4) * 10 / sqrt(5) = 2.132 * 4.472
    expect(small.high - 5).toBeCloseTo(9.535, 2);
  });

  it("needs two observations and a finite spread", () => {
    expect(ci90(5, 10, 1)).toBeNull();
    expect(ci90(5, null, 10)).toBeNull();
    expect(ci90(5, Number.NaN, 10)).toBeNull();
  });
});
