import { describe, expect, it } from "vitest";
import { normalizeQuery, tagPull } from "./games";

describe("tagPull", () => {
  it("is the prediction minus the prediction without the tag", () => {
    // logit(0.785) = 1.296; without a +0.4 tag: expit(0.896) = 0.710
    expect(tagPull(78.5, 0.4)!).toBeCloseTo(7.5, 1);
    expect(tagPull(78.5, -0.4)!).toBeLessThan(0);
    expect(tagPull(78.5, null)).toBeNull();
  });

  it("is compressed near the top of the scale", () => {
    expect(Math.abs(tagPull(95, 0.4)!)).toBeLessThan(Math.abs(tagPull(70, 0.4)!));
  });
});

describe("normalizeQuery", () => {
  it("lower-cases, trims and strips accents", () => {
    expect(normalizeQuery("  Pokémon ")).toBe("pokemon");
    expect(normalizeQuery("ÉLDEN")).toBe("elden");
  });
});
