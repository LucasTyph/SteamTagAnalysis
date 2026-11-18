import * as Plot from "@observablehq/plot";
import { useEffect, useRef } from "react";
import type { TagCurve } from "../data/timelines";
import { SERIES_COLORS } from "../lib/colors";

const SMOOTH = 7;
const HALF = (SMOOTH - 1) / 2;

interface Props {
  curves: TagCurve[];
  maxMonths?: number;
}

/** Average monthly % positive by months since first review, one line per tag. */
export function TagCurves({ curves, maxMonths = 72 }: Props) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el || !curves.length) return;
    // Each tag has only a few dozen games, so month-to-month averages are noisy:
    // show a centred moving average over `SMOOTH` months.
    const rows = curves.flatMap((c) => {
      const pts = c.points.filter(([m]) => m <= maxMonths);
      return pts.map(([m, n], i) => {
        const win = pts.slice(Math.max(0, i - HALF), i + HALF + 1);
        const avg = (k: number) => win.reduce((s, p) => s + p[k], 0) / win.length;
        return { tag: c.name, m, n, mean: avg(2), p25: avg(3), p75: avg(4) };
      });
    });
    const plot = Plot.plot({
      width: el.clientWidth || 800,
      height: 320,
      marginLeft: 40,
      x: { label: "Months since first review →", grid: true },
      y: { label: "↑ Average % positive", grid: true },
      color: { domain: curves.map((c) => c.name), range: SERIES_COLORS, legend: true },
      marks: [
        curves.length === 1
          ? Plot.areaY(rows, { x: "m", y1: "p25", y2: "p75", fill: SERIES_COLORS[0], fillOpacity: 0.15, curve: "monotone-x" })
          : null,
        Plot.line(rows, { x: "m", y: "mean", stroke: "tag", strokeWidth: 1.8, curve: "monotone-x" }),
        Plot.tip(
          rows,
          Plot.pointerX({
            x: "m",
            y: "mean",
            stroke: "tag",
            title: (r) => `${r.tag}, month ${r.m}\naverage ${r.mean.toFixed(1)}% (middle half ${r.p25.toFixed(0)}–${r.p75.toFixed(0)}%)\n${r.n} games`,
          }),
        ),
      ],
      style: { background: "transparent", fontSize: "12px" },
    });
    el.replaceChildren(plot);
    return () => plot.remove();
  }, [curves, maxMonths]);

  return <div className="plot" ref={ref} />;
}
