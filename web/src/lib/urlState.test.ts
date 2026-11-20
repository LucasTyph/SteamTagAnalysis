import { describe, expect, it } from "vitest";
import { DEFAULT_FILTERS, type Tag } from "../data/queries";
import { gameHref, parseFilters, parseTags, toParams } from "./urlState";
import type { TagIndex } from "./useTags";

const tag = (tagid: number, name: string): Tag => ({ tagid, name, n_games: 1, n_devs: 1, mean_score: 80, coef: 0 });
const list = [tag(1, "Roguelike"), tag(2, "Deckbuilding"), tag(3, "Tower Defense")];
const tags: TagIndex = {
  list,
  byId: new Map(list.map((t) => [t.tagid, t])),
  byName: new Map(list.map((t) => [t.name.toLowerCase(), t])),
};

describe("URL state", () => {
  it("round-trips tags and filters", () => {
    const filters = { ...DEFAULT_FILTERS, yearFrom: 2018, price: "paid" as const, minReviews: 100 };
    const p = toParams([list[0], list[2]], filters);
    expect(parseTags(p, tags).map((t) => t.name)).toEqual(["Roguelike", "Tower Defense"]);
    expect(parseFilters(p)).toEqual(filters);
  });

  it("leaves defaults out of the URL and ignores junk", () => {
    expect(toParams([], DEFAULT_FILTERS).toString()).toBe("");
    const p = new URLSearchParams("tags=roguelike,Nope,ROGUELIKE&price=cheap&min=abc&ea=only");
    expect(parseTags(p, tags).map((t) => t.tagid)).toEqual([1]);
    expect(parseFilters(p)).toEqual({ ...DEFAULT_FILTERS, earlyAccess: "only" });
  });

  it("builds game links from integer app IDs", () => {
    expect(gameHref(1145360.7)).toBe("/games/1145360");
  });
});
