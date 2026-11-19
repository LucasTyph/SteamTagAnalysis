// Review-timeline data (web/public/data/timelines/), produced by `stp export`.
import { dataUrl } from "./url";

export interface TimelineSummary {
  appid: number;
  name: string;
  developer: string | null;
  first: string; // "YYYY-MM"
  last: string;
  reviews: number;
  overall: number;
  launch: number | null;
  recent: number | null;
  drift: number | null;
  trough: number | null;
  trough_month: string | null;
  peak: number | null;
  recovery: number | null;
  decline: number | null;
  volatility: number | null;
  changes: number;
  tags: string[];
}

export interface Announcement {
  date: string; // "YYYY-MM-DD"
  title: string;
  url: string;
  kind: "update" | "launch";
}

export interface TurningPoint {
  month: string;
  before: number;
  after: number;
  news: Announcement | null;
}

export interface TimelineDetail {
  appid: number;
  months: [string, number, number][]; // [YYYY-MM, up, down]
  changes: TurningPoint[];
  news: Announcement[];
}

export interface TagCurve {
  tagid: number;
  name: string;
  points: [number, number, number, number, number][]; // [month, n_games, mean, p25, p75]
}

let indexPromise: Promise<TimelineSummary[]> | null = null;
export function loadTimelineIndex(): Promise<TimelineSummary[]> {
  // Stored column-oriented ({cols, rows}) to keep the download small.
  indexPromise ??= fetch(dataUrl("timelines/index.json"))
    .then((r) => r.json())
    .then((d: { cols: (keyof TimelineSummary)[]; rows: unknown[][] }) =>
      d.rows.map((row) => Object.fromEntries(d.cols.map((c, i) => [c, row[i]])) as unknown as TimelineSummary),
    );
  return indexPromise;
}

const detailCache = new Map<number, Promise<TimelineDetail>>();
export function loadTimeline(appid: number): Promise<TimelineDetail> {
  let p = detailCache.get(appid);
  if (!p) {
    p = fetch(dataUrl(`timelines/${Math.trunc(appid)}.json`)).then((r) => {
      if (!r.ok) throw new Error(`No timeline for app ${appid}`);
      return r.json();
    });
    detailCache.set(appid, p);
  }
  return p;
}

let curvesPromise: Promise<TagCurve[]> | null = null;
export function loadTagCurves(): Promise<TagCurve[]> {
  curvesPromise ??= fetch(dataUrl("timelines/tag_curves.json")).then((r) => r.json());
  return curvesPromise;
}

// --- helpers ----------------------------------------------------------------------

export const MIN_MONTH_REVIEWS = 20;

export function monthDate(ym: string): Date {
  const [y, m] = ym.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, 1));
}

export function monthsBetween(a: string, b: string): number {
  const [ya, ma] = a.split("-").map(Number);
  const [yb, mb] = b.split("-").map(Number);
  return (yb - ya) * 12 + (mb - ma);
}

export interface MonthPoint {
  ym: string;
  date: Date;
  sinceLaunch: number;
  reviews: number;
  pct: number | null; // null when the month (or window) has too few reviews
}

/** Monthly positive %, optionally as a trailing 3-month window (sum-based). */
export function monthlySeries(detail: TimelineDetail, smooth: boolean): MonthPoint[] {
  const months = detail.months;
  if (!months.length) return [];
  const first = months[0][0];
  const window = smooth ? 3 : 1;
  return months.map(([ym, up, down], i) => {
    let u = 0;
    let n = 0;
    for (let j = Math.max(0, i - window + 1); j <= i; j++) {
      // Only count months that are actually adjacent (gaps have no rows).
      if (monthsBetween(months[j][0], ym) < window) {
        u += months[j][1];
        n += months[j][1] + months[j][2];
      }
    }
    return {
      ym,
      date: monthDate(ym),
      sinceLaunch: monthsBetween(first, ym),
      reviews: up + down,
      pct: n >= MIN_MONTH_REVIEWS ? (100 * u) / n : null,
    };
  });
}

export function fmtMonth(ym: string | null | undefined): string {
  if (!ym) return "–";
  return monthDate(ym).toLocaleDateString("en-US", { month: "short", year: "numeric", timeZone: "UTC" });
}
