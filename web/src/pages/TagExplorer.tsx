import { useCallback, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { CompanionScatter } from "../components/CompanionScatter";
import { EffectBar } from "../components/EffectBar";
import { FiltersBar } from "../components/FiltersBar";
import { ErrorNote, Loading } from "../components/Loading";
import { TagNetwork } from "../components/TagNetwork";
import { TagPicker } from "../components/TagPicker";
import {
  type Companion,
  type Filters,
  type Tag,
  comboStats,
  companions as fetchCompanions,
  gamesIn,
  loadMeta,
  pairEdges,
} from "../data/queries";
import { effectTone, fmtInt, fmtPct, fmtPp } from "../lib/format";
import { useAsync } from "../lib/hooks";
import { type TagIndex, useTags } from "../lib/useTags";
import { gameHref, parseFilters, parseTags, toParams } from "../lib/urlState";
import { usePageMeta } from "../lib/pageMeta";

const MAX_TAGS = 4;
const MIN_DEVS = 5;

export function TagExplorer() {
  usePageMeta("Tag Explorer");
  const tags = useTags();
  if (tags.error) return <ErrorNote error={tags.error} />;
  if (!tags.data) return <Loading label="Loading tags…" />;
  return <Explorer tags={tags.data} />;
}

function Explorer({ tags }: { tags: TagIndex }) {
  const [params, setParams] = useSearchParams();
  const selected = useMemo(() => parseTags(params, tags), [params, tags]);
  const filters = useMemo(() => parseFilters(params), [params]);
  usePageMeta(
    selected.length ? `${selected.map((t) => t.name).join(" + ")} · Tag Explorer` : "Tag Explorer",
    "How Steam games with a mix of tags are reviewed, and whether the mix beats its parts.",
  );
  const update = (t: Tag[], f: Filters) => setParams(toParams(t, f));

  return (
    <section className="page">
      <header className="page-header">
        <h1>Tag Explorer</h1>
        <p className="lede">
          Pick up to {MAX_TAGS} Steam tags to see how games with that mix are reviewed, and whether
          the mix does better or worse than its individual tags predict.
        </p>
      </header>
      <div className="controls">
        <TagPicker
          tags={tags}
          selected={selected}
          max={MAX_TAGS}
          onChange={(t) => update(t, filters)}
          placeholder="Type a tag, e.g. Roguelike…"
        />
        <FiltersBar filters={filters} onChange={(f) => update(selected, f)} />
      </div>
      {selected.length === 0 ? (
        <Landing tags={tags} onSelect={(t) => update([t], filters)} />
      ) : (
        <ComboView
          key={selected.map((t) => t.tagid).join(",")}
          tags={tags}
          selected={selected}
          filters={filters}
          onAdd={(t) => selected.length < MAX_TAGS && update([...selected, t], filters)}
        />
      )}
    </section>
  );
}

function Landing({ tags, onSelect }: { tags: TagIndex; onSelect: (t: Tag) => void }) {
  const top = useMemo(() => [...tags.list].sort((a, b) => b.n_devs - a.n_devs).slice(0, 110), [tags]);
  const network = useAsync(
    async () => ({ edges: await pairEdges(top.map((t) => t.tagid)), meta: await loadMeta() }),
    [top],
  );
  const starters = ["Roguelike Deckbuilder", "Farming Sim", "Tower Defense", "Metroidvania", "Horror", "Visual Novel", "City Builder", "Souls-like"]
    .map((n) => tags.byName.get(n.toLowerCase()))
    .filter((t): t is Tag => !!t);

  return (
    <div className="landing">
      <div className="starters">
        <span className="muted">Try:</span>
        {starters.map((t) => (
          <button key={t.tagid} type="button" className="chip" onClick={() => onSelect(t)}>
            {t.name}
          </button>
        ))}
      </div>
      <h2>How tags cluster</h2>
      {network.error && <ErrorNote error={network.error} />}
      {network.loading && <Loading label="Starting the query engine (first load takes a few seconds)…" />}
      {network.data && (
        <TagNetwork
          tags={top}
          edges={network.data.edges}
          totalGames={Number(network.data.meta.counts.games)}
          onSelect={onSelect}
        />
      )}
    </div>
  );
}

type SortKey = "gain" | "drop" | "common" | "effect";

function ComboView({
  tags,
  selected,
  filters,
  onAdd,
}: {
  tags: TagIndex;
  selected: Tag[];
  filters: Filters;
  onAdd: (t: Tag) => void;
}) {
  const ids = selected.map((t) => t.tagid);
  const fkey = JSON.stringify(filters);
  const stats = useAsync(() => comboStats(ids, filters), [ids.join(), fkey]);
  const comps = useAsync(() => fetchCompanions(ids, filters, MIN_DEVS), [ids.join(), fkey]);
  const games = useAsync(() => gamesIn(ids, filters, 40), [ids.join(), fkey]);
  const [sort, setSort] = useState<SortKey>("gain");
  const tagName = useCallback((id: number) => tags.byId.get(id)?.name ?? `#${id}`, [tags]);
  const pick = useCallback((id: number) => {
    const t = tags.byId.get(id);
    if (t) onAdd(t);
  }, [tags, onAdd]);

  if (stats.error) return <ErrorNote error={stats.error} />;
  if (!stats.data) return <Loading label="Starting the query engine (first load takes a few seconds)…" />;
  const s = stats.data;
  const tooFew = s.n_devs < MIN_DEVS;
  const tone = effectTone(s.ci?.low, s.ci?.high);

  const sorted = [...(comps.data ?? [])].sort((a: Companion, b: Companion) => {
    if (sort === "common") return b.n_devs - a.n_devs;
    if (sort === "effect") return (b.ci?.low ?? -99) - (a.ci?.low ?? -99);
    if (sort === "drop") return (a.score ?? 0) - (b.score ?? 0);
    return (b.score ?? 0) - (a.score ?? 0);
  });

  return (
    <div className="combo">
      <div className="cards">
        <Card label="Games" value={fmtInt(s.n_games)} />
        <Card label="Developers" value={fmtInt(s.n_devs)} hint="each developer counts once" />
        <Card label="Average score" value={fmtPct(s.score)} hint="review score, small games adjusted" />
        <Card label="Predicted from tags" value={fmtPct(s.predicted)} />
        <Card
          label="Mix effect"
          value={fmtPp(s.effect)}
          tone={tone}
          hint={
            (s.ci ? `90% CI ${fmtPp(s.ci.low)} to ${fmtPp(s.ci.high)}` : "not enough data") +
            (s.live && selected.length > 1 ? " · live estimate, reads slightly low" : "")
          }
        />
      </div>
      {selected.length === 1 && (
        <p className="note">
          With a single tag the model already accounts for it, so the mix effect is close to zero by
          design. Add a second tag to see whether the combination beats its parts.
        </p>
      )}
      {tooFew && (
        <p className="note warn">
          Only {s.n_devs} developer{s.n_devs === 1 ? "" : "s"} made games with this mix, which is too few
          for reliable statistics (minimum {MIN_DEVS}).
        </p>
      )}

      {selected.length < MAX_TAGS && !tooFew && (
        <div className="panel">
          <div className="panel-header">
            <h2>Add one more tag</h2>
            <div className="segmented" role="tablist" aria-label="Sort companions">
              {(
                [
                  ["gain", "Highest score"],
                  ["drop", "Lowest score"],
                  ["effect", "Strongest effect"],
                  ["common", "Most common"],
                ] as [SortKey, string][]
              ).map(([k, label]) => (
                <button key={k} type="button" role="tab" aria-selected={sort === k} onClick={() => setSort(k)}>
                  {label}
                </button>
              ))}
            </div>
          </div>
          {comps.loading && <Loading label="Comparing tags…" />}
          {comps.data && comps.data.length === 0 && <p className="muted">No tag adds enough developers.</p>}
          {comps.data && comps.data.length > 0 && (
            <div className="two-col">
              <CompanionScatter companions={comps.data} tagName={tagName} baseScore={s.score} onPick={pick} />
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>+ Tag</th>
                      <th className="num">Devs</th>
                      <th className="num">Score</th>
                      <th className="num">vs now</th>
                      <th>Mix effect (90% CI)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sorted.slice(0, 15).map((c) => (
                      <tr key={c.tagid}>
                        <td>
                          <button type="button" className="link" onClick={() => pick(c.tagid)}>
                            {tagName(c.tagid)}
                          </button>
                        </td>
                        <td className="num">{fmtInt(c.n_devs)}</td>
                        <td className="num">{fmtPct(c.score)}</td>
                        <td className="num">{fmtPp((c.score ?? 0) - (s.score ?? 0))}</td>
                        <td>
                          <EffectBar effect={c.effect} low={c.ci?.low} high={c.ci?.high} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}

      <div className="panel">
        <h2>Most-reviewed games with this mix</h2>
        {games.loading && <Loading label="Finding games…" />}
        {games.data && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Game</th>
                  <th>Developer</th>
                  <th className="num">Year</th>
                  <th className="num">Reviews</th>
                  <th className="num">Positive</th>
                  <th className="num">vs predicted</th>
                </tr>
              </thead>
              <tbody>
                {games.data.map((g) => (
                  <tr key={g.appid}>
                    <td>
                      <Link to={gameHref(g.appid)}>{g.name}</Link>
                    </td>
                    <td className="muted">{g.developer ?? "–"}</td>
                    <td className="num">{g.year ?? "–"}</td>
                    <td className="num">{fmtInt(g.review_count)}</td>
                    <td className="num">{g.pct_positive}%</td>
                    <td className={`num tone-${g.resid > 3 ? "positive" : g.resid < -3 ? "negative" : "neutral"}`}>
                      {fmtPp(g.resid)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function Card({ label, value, hint, tone }: { label: string; value: string; hint?: string; tone?: string }) {
  return (
    <div className={`card${tone ? ` tone-${tone}` : ""}`}>
      <div className="card-label">{label}</div>
      <div className="card-value">{value}</div>
      {hint && <div className="card-hint">{hint}</div>}
    </div>
  );
}
