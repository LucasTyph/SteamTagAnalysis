import * as Plot from "@observablehq/plot";
import { useEffect, useRef } from "react";
import { type MonthPoint, type TurningPoint, fmtMonth, monthDate } from "../data/timelines";
import { NEG, POS, SERIES_COLORS } from "../lib/colors";

export interface Series {
  name: string;
  points: MonthPoint[];
  changes?: TurningPoint[];
  firstMonth: string;
}

interface Props {
  series: Series[];
  align: "calendar" | "launch";
  showVolume?: boolean;
}

/** Monthly % positive per game; turning points marked when a single game is shown. */
export function TimelineChart({ series, align, showVolume = true }: Props) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el || !series.length) return;
    const width = el.clientWidth || 800;
    const byLaunch = align === "launch";
    const rows = series.flatMap((s, i) =>
      s.points.map((p) => ({
        game: s.name,
        color: SERIES_COLORS[i % SERIES_COLORS.length],
        x: byLaunch ? p.sinceLaunch : p.date,
        pct: p.pct ?? Number.NaN,
        reviews: p.reviews,
        ym: p.ym,
      })),
    );
    const single = series.length === 1 ? series[0] : null;
    const pctAt = new Map((single?.points ?? []).map((p) => [p.ym, p.pct]));
    const changes = (single?.changes ?? []).map((c) => ({
      ...c,
      // Place the marker on the line itself (falls back to the new segment's level).
      y: pctAt.get(c.month) ?? c.after,
      x: byLaunch ? monthsSince(single!.firstMonth, c.month) : monthDate(c.month),
      color: c.after >= c.before ? POS : NEG,
      label:
        `${fmtMonth(c.month)}: ${c.before.toFixed(0)}% → ${c.after.toFixed(0)}%` +
        (c.news ? `\nNearest announcement (${c.news.date}):\n${truncate(c.news.title, 60)}` : "\nNo update announced nearby"),
    }));
    const xOpts = byLaunch
      ? { label: "Months since first review →", grid: true }
      : { type: "utc" as const, label: null, grid: true };

    const main = Plot.plot({
      width,
      height: 340,
      marginLeft: 40,
      x: xOpts,
      y: { domain: [0, 100], label: "↑ % positive", grid: true },
      color: series.length > 1 ? { domain: series.map((s) => s.name), range: SERIES_COLORS, legend: true } : undefined,
      marks: [
        Plot.ruleY([50], { stroke: "currentColor", strokeOpacity: 0.2 }),
        Plot.ruleX(changes, { x: "x", stroke: "color", strokeOpacity: 0.35, strokeDasharray: "3,3" }),
        Plot.line(rows, {
          x: "x",
          y: "pct",
          z: "game",
          stroke: series.length > 1 ? "game" : SERIES_COLORS[0],
          strokeWidth: 1.8,
          curve: "monotone-x",
        }),
        Plot.dot(changes, { x: "x", y: "y", fill: "color", r: 5, stroke: "white", strokeWidth: 1 }),
        single
          ? Plot.tip(changes, Plot.pointer({ x: "x", y: "y", title: "label", maxRadius: 18 }))
          : null,
        Plot.tip(
          rows.filter((r) => Number.isFinite(r.pct)),
          Plot.pointerX({
            x: "x",
            y: "pct",
            stroke: "color",
            title: (r) => `${series.length > 1 ? `${r.game}\n` : ""}${fmtMonth(r.ym)}: ${r.pct.toFixed(1)}% positive\n${r.reviews.toLocaleString("en-US")} reviews`,
          }),
        ),
      ],
      style: { background: "transparent", fontSize: "12px" },
    });

    const nodes: Element[] = [main];
    if (showVolume && single) {
      const vol = Plot.plot({
        width,
        height: 90,
        marginLeft: 40,
        x: xOpts,
        y: { label: "Reviews", grid: true, tickFormat: "~s", ticks: 3 },
        marks: [
          Plot.rectY(
            rows,
            byLaunch
              ? { x1: (r) => r.x as number, x2: (r) => (r.x as number) + 1, y: "reviews", fill: "currentColor", fillOpacity: 0.35 }
              : { x: "x", y: "reviews", interval: "month", fill: "currentColor", fillOpacity: 0.35 },
          ),
        ],
        style: { background: "transparent", fontSize: "11px" },
      });
      nodes.push(vol);
    }
    el.replaceChildren(...nodes);
    return () => nodes.forEach((n) => n.remove());
  }, [series, align, showVolume]);

  return <div className="plot timeline-chart" ref={ref} />;
}

function monthsSince(first: string, ym: string): number {
  const [ya, ma] = first.split("-").map(Number);
  const [yb, mb] = ym.split("-").map(Number);
  return (yb - ya) * 12 + (mb - ma);
}

function truncate(s: string, n: number): string {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}
