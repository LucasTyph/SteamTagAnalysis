import { beforeEach, describe, expect, it, vi } from "vitest";

// Stand-in for DuckDB-WASM: record each SQL statement and answer from a handler.
const calls: string[] = [];
let answer: (sql: string) => unknown[] = () => [];
vi.mock("./db", () => ({
  query: async (sql: string) => {
    calls.push(sql);
    return answer(sql);
  },
}));

const { DEFAULT_FILTERS, comboStats, companions, isDefaultFilters } = await import("./queries");

const PRE = { n_games: 21, n_devs: 19, score: 82.8, predicted: 76.0, effect: 6.8, low: 3.5, high: 10.1 };
const LIVE = { n_games: 21, n_devs: 19, score: 82.8, predicted: 76.4, effect: 6.4, sd: 8 };

beforeEach(() => {
  calls.length = 0;
  answer = () => [];
});

describe("comboStats", () => {
  it("uses the precomputed leave-mix-out effect for a pair with default filters", async () => {
    answer = (sql) => (sql.includes("FROM combos") ? [PRE] : [LIVE]);
    const s = await comboStats([7, 3], DEFAULT_FILTERS);
    expect(s).toEqual({ n_games: 21, n_devs: 19, score: 82.8, predicted: 76.0, effect: 6.8, ci: { low: 3.5, high: 10.1 } });
    expect(calls).toHaveLength(1);
    expect(calls[0]).toMatch(/t1 = 3 AND t2 = 7 AND t3 IS NULL/); // ids sorted
  });

  it("falls back to the live estimate (flagged) when filtered or not precomputed", async () => {
    answer = (sql) => (sql.includes("FROM combos") ? [] : [LIVE]);
    const missing = await comboStats([3, 7], DEFAULT_FILTERS);
    expect(missing.live).toBe(true);
    expect(missing.effect).toBe(6.4);

    calls.length = 0;
    const filtered = await comboStats([3, 7], { ...DEFAULT_FILTERS, yearFrom: 2020 });
    expect(filtered.live).toBe(true);
    expect(calls.some((sql) => sql.includes("FROM combos"))).toBe(false);
    expect(calls[0]).toMatch(/g\.year >= 2020/);
  });

  it("forces tag IDs to integers before they reach SQL", async () => {
    answer = () => [LIVE];
    await comboStats([3, 7, 9, 11].map((t) => t + 0.5), DEFAULT_FILTERS);
    expect(calls[0]).toMatch(/tagid IN \(3,7,9,11\)/);
  });
});

describe("companions", () => {
  it("replaces live companions with precomputed ones where they exist", async () => {
    answer = (sql) =>
      sql.includes("FROM combos")
        ? [{ tagid: 5, ...PRE }]
        : [
            { tagid: 5, ...LIVE },
            { tagid: 6, ...LIVE, effect: -2 },
          ];
    const out = await companions([3], DEFAULT_FILTERS);
    expect(out.find((c) => c.tagid === 5)?.effect).toBe(6.8);
    expect(out.find((c) => c.tagid === 6)?.effect).toBe(-2);
  });
});

describe("isDefaultFilters", () => {
  it("treats any change as non-default", () => {
    expect(isDefaultFilters(DEFAULT_FILTERS)).toBe(true);
    expect(isDefaultFilters({ ...DEFAULT_FILTERS, minReviews: 50 })).toBe(false);
  });
});
