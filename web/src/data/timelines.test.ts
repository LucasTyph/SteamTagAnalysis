import { describe, expect, it } from "vitest";
import { type TimelineDetail, fmtMonth, monthlySeries, monthsBetween } from "./timelines";

const detail = (months: [string, number, number][]): TimelineDetail => ({ appid: 1, months, changes: [], news: [] });

describe("monthsBetween", () => {
  it("counts across year boundaries", () => {
    expect(monthsBetween("2019-11", "2020-02")).toBe(3);
    expect(monthsBetween("2020-02", "2020-02")).toBe(0);
  });
});

describe("monthlySeries", () => {
  it("hides months under the 20-review minimum", () => {
    const s = monthlySeries(detail([["2020-01", 30, 10], ["2020-02", 5, 5]]), false);
    expect(s[0].pct).toBeCloseTo(75);
    expect(s[1].pct).toBeNull();
    expect(s[1].sinceLaunch).toBe(1);
  });

  it("smooths over a 3-month window by summing reviews", () => {
    const s = monthlySeries(detail([["2020-01", 10, 0], ["2020-02", 5, 5], ["2020-03", 0, 10]]), true);
    // last point: 15 positive of 30
    expect(s[2].pct).toBeCloseTo(50);
  });

  it("does not smooth across gaps in the history", () => {
    // 2020-02 and 2020-03 are missing, so 2020-04 only sees itself and stays hidden
    const s = monthlySeries(detail([["2020-01", 100, 0], ["2020-04", 5, 5]]), true);
    expect(s[1].pct).toBeNull();
  });
});

describe("fmtMonth", () => {
  it("formats in UTC", () => {
    expect(fmtMonth("2019-08")).toBe("Aug 2019");
    expect(fmtMonth(null)).toBe("–");
  });
});
