import * as Plot from "@observablehq/plot";
import { useEffect, useRef } from "react";
import type { Companion } from "../data/queries";
import { NEG, NEUTRAL, POS } from "../lib/colors";

interface Props {
  companions: Companion[];
  tagName: (id: number) => string;
  baseScore: number | null;
  onPick: (tagid: number) => void;
}

/** Each dot = the current combo plus one more tag: developers (x) vs score (y). */
export function CompanionScatter({ companions, tagName, baseScore, onPick }: Props) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el || !companions.length) return;
    const data = companions
      .filter((c) => c.score != null)
      .map((c) => ({
        ...c,
        name: tagName(c.tagid),
        tone: c.ci && c.ci.low > 0 ? "beats prediction" : c.ci && c.ci.high < 0 ? "misses prediction" : "as predicted",
      }));
    const width = el.clientWidth || 600;
    const plot = Plot.plot({
      width,
      height: 360,
      marginLeft: 44,
      x: { type: "log", label: "Developers with this combo →", grid: true },
      y: { label: "↑ Average score (%)", grid: true },
      color: {
        domain: ["beats prediction", "as predicted", "misses prediction"],
        range: [POS, NEUTRAL, NEG],
        legend: true,
      },
      marks: [
        baseScore != null ? Plot.ruleY([baseScore], { stroke: "currentColor", strokeDasharray: "4,3", strokeOpacity: 0.5 }) : null,
        Plot.dot(data, {
          x: "n_devs",
          y: "score",
          fill: "tone",
          r: 4,
          fillOpacity: 0.75,
          stroke: "currentColor",
          strokeOpacity: 0.15,
          strokeWidth: 0.5,
        }),
        Plot.tip(
          data,
          Plot.pointer({
            x: "n_devs",
            y: "score",
            title: (d: (typeof data)[number]) =>
              `+ ${d.name}\n${d.n_devs} developers · ${d.n_games} games\nscore ${d.score!.toFixed(1)}% · effect ${d.effect! >= 0 ? "+" : ""}${d.effect!.toFixed(1)} pp\nclick to add`,
          }),
        ),
      ],
      style: { background: "transparent", fontSize: "12px" },
    });
    const onClick = () => {
      const v = (plot as unknown as { value?: Companion }).value;
      if (v) onPick(v.tagid);
    };
    plot.addEventListener("click", onClick);
    el.replaceChildren(plot);
    return () => {
      plot.removeEventListener("click", onClick);
      plot.remove();
    };
  }, [companions, tagName, baseScore, onPick]);

  return <div className="plot" ref={ref} />;
}

