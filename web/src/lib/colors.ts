// Diverging score scale centred on the overall mean (~78.5%). The colors are
// mid-tones that read on both light and dark backgrounds.
const LOW = [214, 96, 77]; // warm red
const MID = [150, 150, 160]; // neutral gray
const HIGH = [52, 152, 120]; // teal green

const lerp = (a: number[], b: number[], t: number) =>
  a.map((v, i) => Math.round(v + (b[i] - v) * t));

export function scoreColor(score: number, center = 78.5, spread = 9): string {
  const t = Math.max(-1, Math.min(1, (score - center) / spread));
  const c = t < 0 ? lerp(MID, LOW, -t) : lerp(MID, HIGH, t);
  return `rgb(${c[0]}, ${c[1]}, ${c[2]})`;
}

// Tones for "beats / matches / misses prediction" in charts.
export const POS = "rgb(52, 152, 120)";
export const NEUTRAL = "rgb(150, 150, 160)";
export const NEG = "rgb(214, 96, 77)";
