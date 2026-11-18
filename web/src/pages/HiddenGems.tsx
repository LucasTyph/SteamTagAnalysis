import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { EffectBar } from "../components/EffectBar";
import { ErrorNote, Loading } from "../components/Loading";
import { TagPicker } from "../components/TagPicker";
import { type GemQuery, type PrecomputedCombo, type Tag, rankedCombos } from "../data/queries";
import { fmtInt, fmtPct } from "../lib/format";
import { type TagIndex, useAsync, useTags } from "../lib/hooks";
import { exploreHref } from "../lib/urlState";

export function HiddenGems() {
  const tags = useTags();
  if (tags.error) return <ErrorNote error={tags.error} />;
  if (!tags.data) return <Loading label="Loading tags…" />;
  return <Gems tags={tags.data} />;
}

const DEV_LIMITS = [
  [30, "Tiny niches (≤ 30 developers)"],
  [100, "Niches (≤ 100)"],
  [100000, "Any size"],
] as const;

function Gems({ tags }: { tags: TagIndex }) {
  const [direction, setDirection] = useState<GemQuery["direction"]>("best");
  const [sizes, setSizes] = useState<number[]>([2, 3]);
  const [maxDevs, setMaxDevs] = useState<number>(100);
  const [minScore, setMinScore] = useState(85);
  const [focus, setFocus] = useState<Tag[]>([]);

  const q: GemQuery = {
    direction,
    sizes,
    maxDevs,
    minScore,
    includeTag: focus[0]?.tagid ?? null,
    limit: 60,
  };
  const result = useAsync(() => rankedCombos(q), [JSON.stringify(q)]);

  const toggleSize = (s: number) =>
    setSizes((cur) => (cur.includes(s) ? (cur.length > 1 ? cur.filter((x) => x !== s) : cur) : [...cur, s].sort()));

  return (
    <section className="page">
      <header className="page-header">
        <h1>{direction === "best" ? "Hidden Gems" : "Cursed Combos"}</h1>
        <p className="lede">
          {direction === "best"
            ? "Tag mixes whose games are reviewed clearly better than their individual tags predict, ranked by how confident that is."
            : "Tag mixes whose games are reviewed clearly worse than their individual tags predict."}{" "}
          Each developer counts once, near-synonym pairs (like Roguelike + Roguelite) are left out, and
          only results that survive a false-discovery correction (q &lt; 0.1) are shown.
        </p>
      </header>

      <div className="controls gem-controls">
        <div className="segmented" role="tablist" aria-label="Direction">
          <button type="button" role="tab" aria-selected={direction === "best"} onClick={() => setDirection("best")}>
            Beat their parts
          </button>
          <button type="button" role="tab" aria-selected={direction === "worst"} onClick={() => setDirection("worst")}>
            Miss their parts
          </button>
        </div>
        <div className="segmented" role="group" aria-label="Combo size">
          <button type="button" aria-pressed={sizes.includes(2)} onClick={() => toggleSize(2)}>
            Pairs
          </button>
          <button type="button" aria-pressed={sizes.includes(3)} onClick={() => toggleSize(3)}>
            Triples
          </button>
        </div>
        <label className="inline">
          Size
          <select value={maxDevs} onChange={(e) => setMaxDevs(Number(e.target.value))}>
            {DEV_LIMITS.map(([v, label]) => (
              <option key={v} value={v}>
                {label}
              </option>
            ))}
          </select>
        </label>
        {direction === "best" && (
          <label className="inline">
            Min. score
            <select value={minScore} onChange={(e) => setMinScore(Number(e.target.value))}>
              {[0, 80, 85, 90].map((v) => (
                <option key={v} value={v}>
                  {v ? `${v}%+` : "any"}
                </option>
              ))}
            </select>
          </label>
        )}
        <div className="focus-picker">
          <TagPicker tags={tags} selected={focus} onChange={setFocus} max={1} placeholder="Containing tag… (optional)" />
        </div>
      </div>

      {result.error && <ErrorNote error={result.error} />}
      {result.loading && !result.data && <Loading label="Starting the query engine (first load takes a few seconds)…" />}
      {result.data && <GemList combos={result.data} tags={tags} />}
    </section>
  );
}

function GemList({ combos, tags }: { combos: PrecomputedCombo[]; tags: TagIndex }) {
  const rows = useMemo(
    () =>
      combos.map((c) => ({
        ...c,
        tags: [c.t1, c.t2, c.t3].filter((t): t is number => t != null).map((t) => tags.byId.get(t)!).filter(Boolean),
      })),
    [combos, tags],
  );
  if (!rows.length) return <p className="muted">No combos match these settings.</p>;
  return (
    <ol className="gem-list">
      {rows.map((c, i) => (
        <li key={`${c.t1}-${c.t2}-${c.t3}`} className="gem">
          <span className="gem-rank">{i + 1}</span>
          <div className="gem-tags">
            {c.tags.map((t) => (
              <span key={t.tagid} className="chip">
                {t.name}
              </span>
            ))}
          </div>
          <div className="gem-stats">
            <span title="Average score of the combo's games (developer-weighted)">
              <strong>{fmtPct(c.mean_score)}</strong> <span className="muted">score</span>
            </span>
            <span className="muted" title="Score the additive tag model predicts">
              predicted {fmtPct(c.mean_predicted)}
            </span>
            <EffectBar effect={c.effect} low={c.ci_low} high={c.ci_high} range={15} />
            <span className="muted">
              {fmtInt(c.n_devs)} devs · {fmtInt(c.n_games)} games
              {c.median_year ? ` · median ${c.median_year}` : ""}
            </span>
          </div>
          <Link className="gem-link" to={exploreHref(c.tags)}>
            Explore →
          </Link>
        </li>
      ))}
    </ol>
  );
}
