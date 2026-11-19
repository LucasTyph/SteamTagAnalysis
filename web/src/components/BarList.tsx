import type { ReactNode } from "react";
import { fmtPct, fmtPp } from "../lib/format";

export interface BarRow {
  label: ReactNode;
  value: number;
  note?: string;
  /** Needed when the label isn't a string. */
  key?: string | number;
}

/** Horizontal bars on a percent scale, or diverging around zero (signed pp). */
export function BarList({
  rows,
  diverging = false,
  minScale = 0,
}: {
  rows: BarRow[];
  diverging?: boolean;
  /** Smallest half-width (diverging) so small values don't fill the track. */
  minScale?: number;
}) {
  const max = Math.max(minScale, ...rows.map((r) => Math.abs(r.value)));
  return (
    <ul className={`bar-list${diverging ? " diverging" : ""}`}>
      {rows.map((r) => {
        // Bars start at zero (percent scale), so lengths compare honestly.
        const pct = diverging ? (Math.abs(r.value) / max) * 50 : Math.max(0, Math.min(100, r.value));
        const tone = diverging ? (r.value >= 0 ? "positive" : "negative") : "neutral";
        return (
          <li key={r.key ?? String(r.label)}>
            <span className="bar-label">{r.label}</span>
            <span className="bar-track">
              <span
                className={`bar tone-${tone}`}
                style={
                  diverging
                    ? r.value >= 0
                      ? { left: "50%", width: `${pct}%` }
                      : { left: `${50 - pct}%`, width: `${pct}%` }
                    : { left: 0, width: `${pct}%` }
                }
              />
            </span>
            <span className="bar-value">{diverging ? fmtPp(r.value) : fmtPct(r.value)}</span>
            {r.note && <span className="bar-note muted">{r.note}</span>}
          </li>
        );
      })}
    </ul>
  );
}
