import * as Plot from "@observablehq/plot";
import { type ReactNode, useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import { BarList } from "../components/BarList";
import { EffectBar } from "../components/EffectBar";
import { ErrorNote, Loading } from "../components/Loading";
import { type ComboFinding, type Findings as Data, loadFindings } from "../data/findings";
import { fmtMonth } from "../data/timelines";
import { fmtInt, fmtPct, fmtPp } from "../lib/format";
import { useAsync } from "../lib/hooks";
import { usePageMeta } from "../lib/pageMeta";

export function Findings() {
  usePageMeta("Findings", "Eight things 60,000 Steam games say about tag mixes, review bombs and which genres age well.");
  const f = useAsync(loadFindings, []);
  if (f.error) return <ErrorNote error={f.error} />;
  if (!f.data) return <Loading label="Loading findings…" />;
  return <FindingsView f={f.data} />;
}

const exploreLink = (tags: string[]) => `/explore?tags=${encodeURIComponent(tags.join(","))}`;

function FindingsView({ f }: { f: Data }) {
  const first = f.year_trend.find((y) => y.games >= 1000) ?? f.year_trend[0];
  const last = f.year_trend[f.year_trend.length - 1];
  const small = f.size_buckets[0];
  const big = f.size_buckets[f.size_buckets.length - 1];
  const bomb = f.bomb_clusters?.[0];
  const aging = f.tag_aging ?? [];
  const agingShown = [...aging.slice(0, 4), ...aging.slice(-4)];

  return (
    <section className="page findings">
      <header className="page-header">
        <h1>Findings</h1>
        <p className="lede">
          What 60,000 Steam games and 120 million reviews say about genre mixes and how reception changes over time.
          Every number below is generated from the data by the pipeline. See the <Link to="/methodology">methodology</Link>{" "}
          for how it's measured and what it can't tell you.
        </p>
      </header>

      <Finding
        n={1}
        title="Newer games are reviewed more kindly"
        lede={
          <>
            The average game released in {last.year} scores <strong>{fmtPct(last.score)}</strong>, against{" "}
            <strong>{fmtPct(first.score)}</strong> for {first.year}. Part of this is survivorship (old games that aged
            badly get delisted or ignored) and part is Steam filtering off-topic review bombs since 2019. But the climb
            is steady across a decade.
          </>
        }
      >
        <YearChart data={f.year_trend.filter((y) => y.games >= 200)} />
      </Finding>

      <Finding
        n={2}
        title="Popular games score higher, but that's mostly selection"
        lede={
          <>
            Games with {small.label} reviews average <strong>{fmtPct(small.score)}</strong>, those with {big.label}{" "}
            average <strong>{fmtPct(big.score)}</strong>. Good games attract players and players write reviews, so
            popularity is a control in the model, not a cause.
          </>
        }
      >
        <BarList
          rows={f.size_buckets.map((b) => ({ label: `${b.label} reviews`, value: b.score, note: `${fmtInt(b.games)} games` }))}
        />
      </Finding>

      <Finding
        n={3}
        title="Some tags lift a game; some weigh it down"
        lede={
          <>
            After controlling for everything else, small, focused genres carry the strongest positive effect and
            online, service-style genres the strongest negative one. {f.tags_worst[0].name} games average{" "}
            <strong>{fmtPct(f.tags_worst[0].mean_score)}</strong>; {f.tags_best[0].name} games{" "}
            <strong>{fmtPct(f.tags_best[0].mean_score)}</strong>.
          </>
        }
      >
        <div className="two-col">
          <TagList title="Strongest lift" tags={f.tags_best} />
          <TagList title="Strongest drag" tags={f.tags_worst} />
        </div>
      </Finding>

      <Finding
        n={4}
        title="Mixes that beat their parts"
        lede={
          <>
            These pairs score clearly above what their two tags predict on their own, made by at least 15 different
            developers each. Read the effect together with the score: {f.pairs_best[0].tags.join(" + ")} beats its
            prediction by {fmtPp(f.pairs_best[0].effect)}, yet still averages only {fmtPct(f.pairs_best[0].score)},
            because it rescues a genre that usually reviews poorly.
          </>
        }
      >
        <ComboList combos={f.pairs_best} />
        <p className="more">
          <Link to="/gems">See every hidden gem →</Link>
        </p>
      </Finding>

      <Finding
        n={5}
        title="…and mixes that miss them"
        lede={
          <>
            The clearest failures are idle and trading games: {f.pairs_worst[0].tags.join(" + ")} lands{" "}
            {Math.abs(f.pairs_worst[0].effect).toFixed(1)} points below its prediction. Most are taskbar idlers built around Steam item
            drops, and players review them as such.
          </>
        }
      >
        <ComboList combos={f.pairs_worst} />
      </Finding>

      {f.drift && f.comebacks && (
        <Finding
          n={6}
          title="Most games don't get better after launch, but comebacks are real"
          lede={
            <>
              Across {fmtInt(f.drift.n)} of the most-reviewed games, the typical change from launch to the last 12
              months is <strong>{fmtPp(f.drift.median_drift)}</strong>. {fmtPct(f.drift.pct_down5, 0)} fell more than
              5 points and {fmtPct(f.drift.pct_up5, 0)} rose more than 5. The exceptions climbed out of very deep holes.
            </>
          }
        >
          <ol className="board">
            {f.comebacks.map((c) => (
              <li key={c.appid}>
                <Link to={`/timelines?games=${c.appid}`}>{c.name}</Link>
                <span className="muted">
                  {fmtPct(c.trough, 0)} in {fmtMonth(c.trough_month)} → {fmtPct(c.recent, 0)} now
                </span>
              </li>
            ))}
          </ol>
        </Finding>
      )}

      {bomb && f.turning_points && (
        <Finding
          n={7}
          title="The biggest drops are review bombs, not patches"
          lede={
            <>
              Of {fmtInt(f.turning_points.n)} detected turning points, {fmtPct(f.turning_points.pct_unmatched, 0)} have
              no update or launch announcement within 45 days. The largest drops cluster in time across unrelated
              games. In {fmtMonth(bomb.month)}, {bomb.n} top games fell by {Math.abs(bomb.avg_shift).toFixed(0)} points on
              average, {bomb.top_publisher_games} of them from {bomb.top_publisher}.
            </>
          }
        >
          <div className="clusters">
            {f.bomb_clusters!.map((c) => (
              <div key={c.month} className="cluster">
                <div className="cluster-head">
                  <strong>{fmtMonth(c.month)}</strong>
                  <span className="muted">
                    {c.n} games · avg {fmtPp(c.avg_shift, 0)}
                  </span>
                </div>
                <p className="muted small">{c.games.join(", ")}</p>
              </div>
            ))}
          </div>
        </Finding>
      )}

      {aging.length > 0 && (
        <Finding
          n={8}
          title="Some genres age better than others"
          lede={
            <>
              Comparing a genre's average score in its first six months with its third and fourth years:{" "}
              {aging[0].name} games gain <strong>{aging[0].change.toFixed(1)} points</strong>, while {aging[aging.length - 1].name}{" "}
              games lose <strong>{Math.abs(aging[aging.length - 1].change).toFixed(1)} points</strong>. These groups are small (
              {Math.min(...agingShown.map((a) => a.n))} to {Math.max(...agingShown.map((a) => a.n))} games each), so treat them as
              hints.
            </>
          }
        >
          <BarList
            diverging
            rows={agingShown.map((a) => ({
              label: a.name,
              value: a.change,
              note: `${a.n} games · ${a.early.toFixed(0)}% → ${a.later.toFixed(0)}%`,
            }))}
          />
          <p className="more">
            <Link to="/timelines">Compare genre trajectories →</Link>
          </p>
        </Finding>
      )}
    </section>
  );
}

function Finding({ n, title, lede, children }: { n: number; title: string; lede: ReactNode; children: ReactNode }) {
  return (
    <article className="finding panel" aria-labelledby={`finding-${n}`}>
      <div className="finding-num" aria-hidden="true">
        {n}
      </div>
      <div className="finding-body">
        <h2 id={`finding-${n}`}>{title}</h2>
        <p className="finding-lede">{lede}</p>
        {children}
      </div>
    </article>
  );
}

function TagList({ title, tags }: { title: string; tags: Data["tags_best"] }) {
  return (
    <div>
      <h3 className="small-heading">{title}</h3>
      <ul className="plain-list">
        {tags.map((t) => (
          <li key={t.name}>
            <Link to={exploreLink([t.name])}>{t.name}</Link>
            <span className="muted">
              {fmtPct(t.mean_score)} avg · {fmtInt(t.n_devs)} devs
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function ComboList({ combos }: { combos: ComboFinding[] }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Mix</th>
            <th className="num">Devs</th>
            <th className="num">Score</th>
            <th className="num">Predicted</th>
            <th>Effect (90% CI)</th>
          </tr>
        </thead>
        <tbody>
          {combos.map((c) => (
            <tr key={c.tags.join("+")}>
              <td>
                <Link to={exploreLink(c.tags)}>{c.tags.join(" + ")}</Link>
              </td>
              <td className="num">{c.n_devs}</td>
              <td className="num">{fmtPct(c.score)}</td>
              <td className="num">{fmtPct(c.predicted)}</td>
              <td>
                <EffectBar effect={c.effect} low={c.ci_low} high={c.ci_high} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Horizontal bars as HTML (labels in text ink; value printed). */
function YearChart({ data }: { data: Data["year_trend"] }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const plot = Plot.plot({
      width: el.clientWidth || 700,
      height: 240,
      marginLeft: 40,
      x: { label: "Release year", tickFormat: "d", grid: false },
      y: { label: "↑ Average score (%)", grid: true, domain: [70, 84] },
      marks: [
        Plot.line(data, { x: "year", y: "score", stroke: "#4a7fb5", strokeWidth: 2 }),
        Plot.dot(data, { x: "year", y: "score", fill: "#4a7fb5", r: 4, stroke: "white", strokeWidth: 1 }),
        Plot.tip(
          data,
          Plot.pointerX({ x: "year", y: "score", title: (d) => `${d.year}: ${d.score}% average\n${d.games.toLocaleString("en-US")} games` }),
        ),
      ],
      style: { background: "transparent", fontSize: "12px" },
    });
    el.replaceChildren(plot);
    return () => plot.remove();
  }, [data]);
  return <div className="plot" ref={ref} role="img" aria-label="Average review score by release year" />;
}
