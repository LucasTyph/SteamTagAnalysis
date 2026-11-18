import { DEFAULT_FILTERS, type Filters, type Tag } from "../data/queries";
import type { TagIndex } from "./hooks";

/** `?tags=Roguelike,Deckbuilding` → Tag[] (unknown names are dropped). */
export function parseTags(params: URLSearchParams, tags: TagIndex): Tag[] {
  const raw = params.get("tags");
  if (!raw) return [];
  const out: Tag[] = [];
  for (const name of raw.split(",")) {
    const t = tags.byName.get(name.trim().toLowerCase());
    if (t && !out.includes(t)) out.push(t);
  }
  return out;
}

const num = (v: string | null) => (v == null || v === "" || Number.isNaN(Number(v)) ? null : Number(v));

export function parseFilters(params: URLSearchParams): Filters {
  const price = params.get("price");
  const ea = params.get("ea");
  return {
    yearFrom: num(params.get("from")),
    yearTo: num(params.get("to")),
    price: price === "free" || price === "paid" ? price : "any",
    earlyAccess: ea === "exclude" || ea === "only" ? ea : "any",
    minReviews: num(params.get("min")) ?? DEFAULT_FILTERS.minReviews,
  };
}

export function toParams(tags: Tag[], f: Filters): URLSearchParams {
  const p = new URLSearchParams();
  if (tags.length) p.set("tags", tags.map((t) => t.name).join(","));
  if (f.yearFrom != null) p.set("from", String(f.yearFrom));
  if (f.yearTo != null) p.set("to", String(f.yearTo));
  if (f.price !== "any") p.set("price", f.price);
  if (f.earlyAccess !== "any") p.set("ea", f.earlyAccess);
  if (f.minReviews !== DEFAULT_FILTERS.minReviews) p.set("min", String(f.minReviews));
  return p;
}

export const exploreHref = (tags: Tag[]) => `/explore?${toParams(tags, DEFAULT_FILTERS)}`;
