import { describe, expect, it } from "vitest";
import { effectTone, fmtInt, fmtPct, fmtPp } from "./format";

describe("formatting", () => {
  it("formats signed percentage points with a real minus sign", () => {
    expect(fmtPp(4.25)).toBe("+4.3 pp");
    expect(fmtPp(-2)).toBe("−2.0 pp");
    expect(fmtPp(0)).toBe("±0.0 pp");
    expect(fmtPp(null)).toBe("–");
  });

  it("formats percentages and integers", () => {
    expect(fmtPct(83.24)).toBe("83.2%");
    expect(fmtPct(83.24, 0)).toBe("83%");
    expect(fmtPct(Number.NaN)).toBe("–");
    expect(fmtInt(59853)).toBe("59,853");
  });

  it("tones an effect only when its interval excludes zero", () => {
    expect(effectTone(0.5, 3)).toBe("positive");
    expect(effectTone(-3, -0.1)).toBe("negative");
    expect(effectTone(-1, 2)).toBe("neutral");
    expect(effectTone(undefined, 2)).toBe("neutral");
  });
});
