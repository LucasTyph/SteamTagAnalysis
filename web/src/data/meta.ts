// meta.json: build/analysis settings and counts. Kept apart from queries.ts so the
// app shell can read it without pulling DuckDB into the main bundle.
import { dataUrl } from "./url";

export interface Meta {
  build: Record<string, unknown>;
  analysis: Record<string, number | string>;
  excluded_tags: string[];
  counts: Record<string, number>;
}

let metaPromise: Promise<Meta> | null = null;
export function loadMeta(): Promise<Meta> {
  metaPromise ??= fetch(dataUrl("meta.json")).then((r) => r.json());
  return metaPromise;
}

/** "November 2026" from build.data_as_of (when the store data was fetched). */
export function dataAsOf(meta: Meta | undefined): string | null {
  const d = meta?.build.data_as_of;
  if (typeof d !== "string") return null;
  return new Date(`${d}T00:00:00Z`).toLocaleDateString("en-US", { month: "long", year: "numeric", timeZone: "UTC" });
}
