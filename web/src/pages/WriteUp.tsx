import { useMemo } from "react";
import { Link } from "react-router-dom";
import { EffectBar } from "../components/EffectBar";
import { ErrorNote, Loading } from "../components/Loading";
import { type Series, TimelineChart } from "../components/TimelineChart";
import { REPO_URL, loadFindings } from "../data/findings";
import { type TimelineDetail, fmtMonth, loadTimeline, monthlySeries } from "../data/timelines";
import { fmtInt, fmtPct } from "../lib/format";
import { useAsync } from "../lib/hooks";
import { usePageMeta } from "../lib/pageMeta";
import { exploreHref, gameHref } from "../lib/urlState";
import { useTags } from "../lib/useTags";

// The argument below is about specific events, so its numbers are fixed as of the date
// it was written. The charts read the live data (past months don't change).
const WRITTEN = "November 2026";

const SHELLS: [string, string, string[]][] = [
  ["Jun 2025", "哪吒传奇", ["Action RPG", "Hack and Slash", "Loot", "Isometric", "RPG"]],
  ["Aug 2025", "烈焰屠龙·神兵觉醒", ["Action RPG", "Hack and Slash", "Loot", "Isometric", "RPG"]],
  ["Nov 2025", "霸世狂刀", ["Action RPG", "Hack and Slash", "Loot", "Isometric", "RPG"]],
  ["Mar 2026", "决战沙城", ["Action RPG", "Hack and Slash", "Loot", "Isometric", "RPG"]],
  ["Mar 2026", "沙城争霸", ["Action RPG", "Hack and Slash", "Loot", "Isometric", "RPG"]],
  ["Jul 2026", "十米爆爽超变", ["Action RPG", "Massively Multiplayer", "Hack and Slash", "Loot", "Isometric"]],
  ["Aug 2026", "猎国沉默专属", ["Action RPG", "Hack and Slash", "Loot", "Isometric", "RPG"]],
  ["Oct 2026", "明月专属传奇", ["Action RPG", "Hack and Slash", "Loot", "Isometric", "RPG"]],
];

const PARADOX: [number, string][] = [
  [394360, "Hearts of Iron IV"],
  [236850, "Europa Universalis IV"],
  [255710, "Cities: Skylines"],
  [281990, "Stellaris"],
];
const NMS = 275850;

export function WriteUp() {
  usePageMeta(
    "What 60,000 Steam games say about genre mixes",
    "A write-up of the Steam Tag Analysis project: the asset-flip trap, publisher-wide review bombs and No Man's Sky's comeback.",
  );
  return (
    <article className="page prose writeup">
      <header className="page-header">
        <p className="kicker">Write-up · {WRITTEN}</p>
        <h1>What 60,000 Steam games say about genre mixes</h1>
        <p className="lede">
          Do some combinations of Steam tags do better than their parts would predict? Answering that took data on
          every game on Steam, a model of what each game&apos;s tags predict, and two lessons about what counts as an
          independent observation.
        </p>
      </header>

      <p>
        Every Steam game carries up to 20 player-voted tags: <em>Roguelike</em>, <em>Cozy</em>, <em>Deckbuilding</em>,{" "}
        <em>Souls-like</em>. A roguelike is reviewed one way and a deckbuilder another. Is a roguelike deckbuilder better or
        worse than the sum? To find out I collected the store data for all ~200,000 apps on Steam and analysed the 60,000
        games with at least 20 reviews, plus month-by-month review history for the 5,000 most-reviewed.
      </p>

      <h2>Measuring &ldquo;better than its parts&rdquo;</h2>
      <p>
        A game&apos;s raw share of positive reviews is noisy when it has few reviews, so each game gets an empirical-Bayes
        score that pulls small games toward the average. A ridge regression then predicts that score from the game&apos;s
        tags, release year, price and popularity. A mix&apos;s <strong>effect</strong> is how far its games land above or
        below the prediction. With about 89,000 pairs and triples tested, a false-discovery correction keeps lucky mixes
        out of the rankings.
      </p>

      <h2>The asset-flip trap</h2>
      <p>
        The first ranking had a clear winner: <strong>FPS + Dating Sim + Strategy</strong>, beating its prediction by 17
        points with a confidence interval barely a point wide. Nearly all of its games came from one studio: about 30
        near-identical adult puzzle games released a week apart, each with its own store page and a handful of reviews.
      </p>
      <p>
        Those 30 games are not 30 observations. They share a developer, a template and an audience, so they agree with
        each other, which is exactly what makes a confidence interval collapse. Counting developers instead of games
        fixed it: each developer&apos;s games are averaged first and intervals are computed across developers. The
        17-point &ldquo;discovery&rdquo; disappeared.
      </p>
      <p>
        The trap came back in another form. Later, four of the top ten mixes were driven by a wave of free Chinese
        &ldquo;Legend&rdquo; (传奇) MMOs. Each was released under a new developer name, the game&apos;s own, so developer
        clustering counted sixteen independent studios:
      </p>
      <figure className="writeup-figure">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Released</th>
                <th>Game (also its developer and publisher)</th>
                <th>Top tags</th>
              </tr>
            </thead>
            <tbody>
              {SHELLS.map(([when, name, tags]) => (
                <tr key={name}>
                  <td>{when}</td>
                  <td>{name}</td>
                  <td className="wrap muted">{tags.join(", ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <figcaption>Eight of the sixteen. All free, all with nearly the same tags in the same order.</figcaption>
      </figure>
      <p>
        The pipeline now groups developer accounts whose games have near-identical tags and release dates and that also
        share a publisher, a near-identical title, or this self-named pattern. 489 accounts collapsed into 155 groups, and
        those mixes left the rankings. The lesson goes beyond Steam: before trusting a ranking, ask what the unit of
        independence is.
      </p>

      <h2>What actually beats its parts</h2>
      <p>
        With those artefacts removed, the mixes that hold up are small and specific. These are the pairs whose whole
        90% interval sits above zero, ranked by how sure that is:
      </p>
      <BestPairs />
      <p>
        Negative effects are bigger and clearer. Idle item-trading apps (<em>Trading + Idler</em>) miss their prediction by
        about 17 points, and VR romance games by about 14. Some positive effects are rescues: MMORPGs score poorly overall,
        and an MMO mix can beat its prediction while still landing below the Steam average, so read every effect next to
        the mix&apos;s actual score.
      </p>
      <p>
        Measuring effects honestly took one more fix. With one shared baseline, a mix&apos;s own games help fit its
        tags&apos; coefficients, so part of a real interaction gets credited to the tags. Each mix is now compared with
        the model refitted <em>without its own games</em> (ridge regression has an exact shortcut for this). Planting a
        known 5-point interaction on random pairs, this recovers 100% of it; the shared baseline recovered 84%.
      </p>

      <h2>Review bombs come in waves</h2>
      <p>
        For the 5,000 most-reviewed games, change-point detection finds the months where a game&apos;s review score
        shifted, and matches each to the nearest update announcement within 45 days. More than half of the 6,055 turning
        points have no update nearby. Looking at <em>when</em> they happen, many line up across games from one publisher.
      </p>
      <p>
        In September 2026, twenty of these games fell by an average of 51 points in the same month. Eleven were Paradox
        titles:
      </p>
      <BombChart />
      <p>
        Hearts of Iron IV usually gets about 3,000 reviews a month. That September it got 42,618, and 95% were negative.
        Ten-year-old games like Crusader Kings II and Victoria II dropped with it. A whole catalogue moving at once, at
        ten times the usual volume, points to a reaction to the publisher rather than to any one game. The data shows the
        same shape for SEGA&apos;s Total War games in August 2019 and 2K&apos;s Borderlands games in April 2025. Scores
        mostly recover within months, but a naive &ldquo;did this update hurt the game?&rdquo; analysis would blame
        whichever patch shipped that month.
      </p>

      <h2>Comebacks are real, but rare</h2>
      <p>
        Across 4,544 games with enough history, the typical game&apos;s last 12 months score 2.7 points below its launch:
        37% fell by more than 5 points and only 14% rose by more than 5. No Man&apos;s Sky is the famous exception, and its
        review history reads like a patch log:
      </p>
      <ComebackChart />
      <p>
        The detection knows none of this history; it only sees monthly review counts, yet the shifts it finds sit next to
        the updates the game is known for. Honesty check: one drop, in December 2017, has no announcement nearby, and
        Beyond&apos;s launch in August 2019 briefly pulled scores down before Synthesis took them to their highest.
      </p>

      <h2>Caveats</h2>
      <p>
        Tags are today&apos;s tags, not the ones a game launched with. Delisted games are missing. And a mix that beats its
        prediction isn&apos;t a recipe: its games may share qualities the tags don&apos;t capture. The{" "}
        <Link to="/methodology">methodology</Link> covers these in detail.
      </p>

      <h2>Try it yourself</h2>
      <p>
        Everything here is live on the site and refreshed monthly: test any mix in the{" "}
        <Link to="/explore">Tag Explorer</Link>, browse <Link to="/gems">Hidden Gems</Link>, look up a game in{" "}
        <Link to="/games">Game Lookup</Link>, compare <Link to="/timelines">review timelines</Link>, or follow{" "}
        <Link to="/releases">new releases</Link> through their first year. The pipeline, tests and notebooks are on{" "}
        <a href={REPO_URL}>GitHub</a>.
      </p>
    </article>
  );
}

function BestPairs() {
  const findings = useAsync(loadFindings, []);
  const tags = useTags();
  if (findings.error) return <ErrorNote error={findings.error} />;
  if (!findings.data || !tags.data) return <Loading label="Loading…" />;
  const byName = tags.data.byName;
  return (
    <figure className="writeup-figure">
      <ul className="writeup-pairs">
        {findings.data.pairs_best.slice(0, 5).map((p) => {
          const mix = p.tags.map((n) => byName.get(n.toLowerCase())).filter((t) => t != null);
          return (
            <li key={p.tags.join("+")}>
              <Link to={exploreHref(mix)}>{p.tags.join(" + ")}</Link>
              <span className="muted">
                {fmtPct(p.score, 0)} vs {fmtPct(p.predicted, 0)} predicted · {fmtInt(p.n_devs)} developers
              </span>
              <EffectBar effect={p.effect} low={p.ci_low} high={p.ci_high} range={15} />
            </li>
          );
        })}
      </ul>
      <figcaption>Current data; the dot is the effect and the line its 90% interval.</figcaption>
    </figure>
  );
}

function BombChart() {
  const details = useAsync(() => Promise.all(PARADOX.map(([id]) => loadTimeline(id))), []);
  const series: Series[] = useMemo(
    () =>
      (details.data ?? []).map((d: TimelineDetail, i) => ({
        name: PARADOX[i][1],
        points: monthlySeries(d, false).filter((p) => p.ym >= "2025-09"),
        firstMonth: d.months[0]?.[0] ?? "2025-09",
      })),
    [details.data],
  );
  if (details.error) return <ErrorNote error={details.error} />;
  if (!details.data) return <Loading label="Loading review history…" />;
  return (
    <figure className="writeup-figure">
      <TimelineChart series={series} align="calendar" showVolume={false} />
      <figcaption>Monthly share of positive reviews for four Paradox games. Hover for review counts.</figcaption>
    </figure>
  );
}

function ComebackChart() {
  const detail = useAsync(() => loadTimeline(NMS), []);
  const series: Series[] = useMemo(
    () =>
      detail.data
        ? [
            {
              name: "No Man's Sky",
              points: monthlySeries(detail.data, true),
              changes: detail.data.changes,
              firstMonth: detail.data.months[0]?.[0] ?? "2016-08",
            },
          ]
        : [],
    [detail.data],
  );
  if (detail.error) return <ErrorNote error={detail.error} />;
  if (!detail.data) return <Loading label="Loading review history…" />;
  return (
    <figure className="writeup-figure">
      <TimelineChart series={series} align="calendar" showVolume={false} />
      <ol className="writeup-changes">
        {detail.data.changes.map((c) => (
          <li key={c.month}>
            <span className={`tone-${c.after >= c.before ? "positive" : "negative"}`}>
              {fmtMonth(c.month)}: {c.before.toFixed(0)}% → {c.after.toFixed(0)}%
            </span>{" "}
            {c.news ? (
              <a href={c.news.url} target="_blank" rel="noreferrer">
                {c.news.title}
              </a>
            ) : (
              <span className="muted">no announcement nearby</span>
            )}
          </li>
        ))}
      </ol>
      <figcaption>
        Positive share by month (3-month window); dots are detected turning points.{" "}
        <Link to={gameHref(NMS)}>More on No Man&apos;s Sky</Link> · <Link to={`/timelines?games=${NMS}`}>full timeline</Link>
      </figcaption>
    </figure>
  );
}

