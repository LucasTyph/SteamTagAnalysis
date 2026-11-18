import { effectTone, fmtPp } from "../lib/format";

interface Props {
  effect: number | null | undefined;
  low: number | null | undefined;
  high: number | null | undefined;
  /** Half-width of the axis in pp. */
  range?: number;
}

/** Inline effect ± 90% CI on a symmetric axis around zero. */
export function EffectBar({ effect, low, high, range = 20 }: Props) {
  if (effect == null) return <span className="muted">–</span>;
  const w = 120;
  const x = (v: number) => ((Math.max(-range, Math.min(range, v)) + range) / (2 * range)) * w;
  const tone = effectTone(low ?? undefined, high ?? undefined);
  return (
    <span className={`effect-bar tone-${tone}`}>
      <svg width={w} height={14} role="img" aria-label={`Effect ${fmtPp(effect)}`}>
        <line x1={x(0)} x2={x(0)} y1={0} y2={14} className="axis" />
        {low != null && high != null && (
          <line x1={x(low)} x2={x(high)} y1={7} y2={7} className="ci" />
        )}
        <circle cx={x(effect)} cy={7} r={3.5} className="dot" />
      </svg>
      <span className="effect-value">{fmtPp(effect)}</span>
    </span>
  );
}
