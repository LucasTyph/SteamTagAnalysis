import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { SteamButton } from "../components/SteamButton";
import { BarList } from "../components/BarList";
import { EffectBar } from "../components/EffectBar";
import { GameSearch } from "../components/GameSearch";
import { ErrorNote, Loading } from "../components/Loading";
import { type Series, TimelineChart } from "../components/TimelineChart";
import {
  type Board,
  type GameCombo,
  type GameDetail,
  gameCombos,
  gameDetail,
  similarGames,
  standouts,
  tagPull,
} from "../data/games";
import { type Tag, loadMeta } from "../data/queries";
import { loadTimeline, loadTimelineIndex, monthlySeries } from "../data/timelines";
import { fmtInt, fmtPct, fmtPp, steamUrl } from "../lib/format";
import { useAsync } from "../lib/hooks";
import { exploreHref, gameHref } from "../lib/urlState";
import { type TagIndex, useTags } from "../lib/useTags";
import { usePageMeta } from "../lib/pageMeta";

const STARTERS: [number, string][] = [
  [1145360, "Hades"],
  [413150, "Stardew Valley"],
  [1091500, "Cyberpunk 2077"],
  [275850, "No Man's Sky"],
  [1794680, "Vampire Survivors"],
  [1086940, "Baldur's Gate 3"],
];

export function Games() {
  const { appid } = useParams();
  const navigate = useNavigate();
  const tags = useTags();
  const meta = useAsync(loadMeta, []);
  const id = appid != null && /^\d+$/.test(appid) ? Number(appid) : null;
  usePageMeta(appid == null ? "Game Lookup" : undefined);

  return (
    <section className="page">
      <header className="page-header">
        <h1>Game Lookup</h1>
        <p className="lede">
          Any of the {meta.data ? fmtInt(meta.data.counts.games) : "~60,000"} games with 20 or more reviews: its tags, how its score compares with what those
          tags predict, the tag mixes it belongs to, and its review history when available.
        </p>
      </header>
      <div className="game-search">
        <GameSearch onPick={(g) => navigate(gameHref(g.appid))} autoFocus={id == null} />
      </div>
      {tags.error && <ErrorNote error={tags.error} />}
      {tags.data &&
        (appid == null ? (
          <Landing />
        ) : id == null ? (
          <p className="note">That isn't a Steam app ID.</p>
        ) : (
          <GameView key={id} appid={id} tags={tags.data} />
        ))}
    </section>
  );
}

// --- landing --------------------------------------------------------------------

const BOARDS: Record<Board, { label: string; note: string }> = {
  over: {
    label: "Beat their tags the most",
    note: "Games with 5,000+ reviews that score furthest above what their tags, year, price and popularity predict.",
  },
  under: {
    label: "Fell furthest short",
    note: "Games with 5,000+ reviews that score furthest below their prediction.",
  },
};

function Landing() {
  const [board, setBoard] = useState<Board>("over");
  const rows = useAsync(() => standouts(board), [board]);
  return (
    <div>
      <div className="starters">
        <span className="muted">Try:</span>
        {STARTERS.map(([id, name]) => (
          <Link key={id} className="chip" to={gameHref(id)}>
            {name}
          </Link>
        ))}
      </div>
      <div className="panel">
        <div className="panel-header">
          <h2>{BOARDS[board].label}</h2>
          <div className="segmented" role="tablist" aria-label="Leaderboard">
            {(Object.keys(BOARDS) as Board[]).map((k) => (
              <button key={k} type="button" role="tab" aria-selected={board === k} onClick={() => setBoard(k)}>
                {BOARDS[k].label}
              </button>
            ))}
          </div>
        </div>
        <p className="muted small">{BOARDS[board].note}</p>
        {rows.error && <ErrorNote error={rows.error} />}
        {!rows.data && !rows.error && <Loading label="Loading the game data…" />}
        {rows.data && (
          <ol className="board">
            {rows.data.map((g) => (
              <li key={g.appid}>
                <Link to={gameHref(g.appid)}>{g.name}</Link>
                <span className="muted">
                  {fmtPct(g.score, 0)} · <span className={`tone-${g.resid >= 0 ? "positive" : "negative"}`}>{fmtPp(g.resid)}</span>
                </span>
              </li>
            ))}
          </ol>
        )}
      </div>
    </div>
  );
}

// --- one game --------------------------------------------------------------------

function GameView({ appid, tags }: { appid: number; tags: TagIndex }) {
  const detail = useAsync(() => gameDetail(appid), [appid]);
  usePageMeta(
    detail.data ? `${detail.data.name} · Game Lookup` : "Game Lookup",
    detail.data
      ? `How ${detail.data.name}'s Steam reviews compare with what its tags predict, and the tag mixes it belongs to.`
      : undefined,
  );
  if (detail.error) return <ErrorNote error={detail.error} />;
  if (detail.data === undefined) return <Loading label="Loading the game data…" />;
  const g = detail.data;
  if (!g) {
    return (
      <p className="note">
        No analysed game has app ID {appid}. Only games with at least 20 reviews are included;{" "}
        <a href={steamUrl(appid)} target="_blank" rel="noreferrer">
          open it on Steam
        </a>{" "}
        instead.
      </p>
    );
  }
  const gameTags = g.tagids.map((t) => tags.byId.get(t)).filter((t): t is Tag => !!t);

  return (
    <div>
      <GameHeader game={g} tags={gameTags} />
      <TagPanel tags={gameTags} />
      <MixPanel game={g} tags={tags} />
      <TimelinePanel appid={g.appid} />
      <SimilarPanel game={g} />
    </div>
  );
}

function GameHeader({ game: g, tags }: { game: GameDetail; tags: Tag[] }) {
  const price = g.is_free ? "Free" : g.price_usd ? `$${g.price_usd.toFixed(2)}` : null;
  const above = g.resid >= 0;
  return (
    <>
      <div className="game-title">
        <div>
          <h2>
            <a href={steamUrl(g.appid)} target="_blank" rel="noreferrer">
              {g.name}
            </a>
          </h2>
          <span className="muted">
            {[g.developer ?? "Unknown developer", g.year, price, g.is_early_access ? "Early access" : null]
              .filter((x) => x != null)
              .join(" · ")}
          </span>
        </div>
        <SteamButton appid={g.appid} name={g.name} />
      </div>
      <div className="cards">
        <Stat label="Steam rating" value={fmtPct(g.pct_positive, 0)} hint={`${fmtInt(g.review_count)} reviews`} />
        <Stat label="Score" value={fmtPct(g.score)} hint={`above ${g.score_pctile.toFixed(0)}% of games`} />
        <Stat label="Predicted from tags" value={fmtPct(g.predicted)} />
        <Stat
          label="vs predicted"
          value={fmtPp(g.resid)}
          hint={`better than ${g.resid_pctile.toFixed(0)}% of games`}
          tone={g.resid > 3 ? "positive" : g.resid < -3 ? "negative" : undefined}
        />
      </div>
      <p>
        Games tagged like this one{tags.length ? ` (${tags.slice(0, 3).map((t) => t.name).join(", ")}…)` : ""}, from the
        same year, price band and popularity, are expected to score about <strong>{fmtPct(g.predicted, 0)}</strong>.{" "}
        {g.name} scores <strong>{Math.abs(g.resid).toFixed(1)} points</strong> {above ? "above" : "below"} that.
        {g.group_devs > 1 ? (
          <>
            {" "}
            Its developer is grouped with {fmtInt(g.group_devs - 1)} other developer{" "}
            {g.group_devs === 2 ? "account" : "accounts"} that release look-alike games ({fmtInt(g.dev_games)} games in
            all), so the group counts as one developer in every statistic (see the{" "}
            <Link to="/methodology">methodology</Link>).
          </>
        ) : (
          g.dev_games > 1 && (
            <>
              {" "}
              Its developer has {fmtInt(g.dev_games - 1)} other {g.dev_games === 2 ? "game" : "games"} in the data.
            </>
          )
        )}
      </p>
    </>
  );
}

function TagPanel({ tags }: { tags: Tag[] }) {
  const meta = useAsync(loadMeta, []);
  if (!meta.data) return null;
  const a = meta.data.analysis;
  // Effects are shown for an average game (the prior mean), so they compare across games.
  const average = (100 * Number(a.prior_alpha)) / (Number(a.prior_alpha) + Number(a.prior_beta));
  const rows = tags
    .map((t) => ({ t, pull: tagPull(average, t.coef) }))
    .filter((r): r is { t: Tag; pull: number } => r.pull != null);
  if (!rows.length) return null;
  return (
    <div className="panel">
      <h2>Its tags</h2>
      <p className="muted small">
        The game's top {tags.length} player-voted tags, in vote order. Each bar is the tag's own effect in the model: how
        much it moves the predicted score of an average game ({fmtPct(average, 0)}), other tags held fixed. Near the
        top of the scale the same effects are compressed.
      </p>
      <BarList
        diverging
        minScale={5}
        rows={rows.map(({ t, pull }) => ({
          key: t.tagid,
          label: <Link to={exploreHref([t])}>{t.name}</Link>,
          value: pull,
          note: `${fmtInt(t.n_games)} games · average ${fmtPct(t.mean_score, 0)}`,
        }))}
      />
      <p className="more">
        <Link to={exploreHref(tags.slice(0, 3))}>Explore its top three tags together →</Link>
      </p>
    </div>
  );
}

const significant = (c: GameCombo) => c.q_value < 0.1 && (c.ci_low > 0 || c.ci_high < 0);

function MixPanel({ game, tags }: { game: GameDetail; tags: TagIndex }) {
  const combos = useAsync(() => gameCombos(game.tagids), [game.appid]);
  const [onlySig, setOnlySig] = useState(true);
  const [showAll, setShowAll] = useState(false);
  const counts = useMemo(() => {
    const all = combos.data ?? [];
    return {
      pairs: all.filter((c) => c.size === 2).length,
      triples: all.filter((c) => c.size === 3).length,
      sig: all.filter(significant).length,
    };
  }, [combos.data]);

  if (combos.error) return <ErrorNote error={combos.error} />;
  if (!combos.data) return <Loading label="Finding its tag mixes…" />;
  if (!combos.data.length) return null;

  const filtered = onlySig ? combos.data.filter(significant) : combos.data;
  const shown = showAll ? filtered : filtered.slice(0, 10);
  const name = (id: number | null) => (id == null ? null : tags.byId.get(id) ?? null);

  return (
    <div className="panel">
      <div className="panel-header">
        <h2>Mixes it belongs to</h2>
        <div className="segmented" role="tablist" aria-label="Which mixes">
          <button type="button" role="tab" aria-selected={onlySig} onClick={() => setOnlySig(true)}>
            Stand out ({counts.sig})
          </button>
          <button type="button" role="tab" aria-selected={!onlySig} onClick={() => setOnlySig(false)}>
            All ({combos.data.length})
          </button>
        </div>
      </div>
      <p className="muted small">
        Its tags form {fmtInt(counts.pairs)} pairs and {fmtInt(counts.triples)} triples with enough games and developers
        to analyse. {counts.sig ? `${counts.sig} score clearly above or below what their tags predict.` : "None of them score clearly above or below what their tags predict."}{" "}
        An effect is how far a mix's games score above or below the additive prediction, with a 90% interval.
      </p>
      {filtered.length === 0 ? (
        <p className="muted">No mix of its tags stands out. Switch to All to see every one.</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Mix</th>
                <th className="num">Games</th>
                <th className="num">Score</th>
                <th>vs predicted</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((c) => {
                const mix = [c.t1, c.t2, c.t3].map(name).filter((t): t is Tag => !!t);
                return (
                  <tr key={`${c.t1}-${c.t2}-${c.t3}`}>
                    <td className="wrap">
                      <Link to={exploreHref(mix)}>{mix.map((t) => t.name).join(" + ")}</Link>
                    </td>
                    <td className="num">
                      {fmtInt(c.n_games)} <span className="muted">· {fmtInt(c.n_devs)} devs</span>
                    </td>
                    <td className="num">{fmtPct(c.mean_score, 0)}</td>
                    <td>
                      <EffectBar effect={c.effect} low={c.ci_low} high={c.ci_high} range={15} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {filtered.length > 10 && (
        <p className="more">
          <button type="button" className="link" onClick={() => setShowAll(!showAll)}>
            {showAll ? "Show fewer" : `Show all ${filtered.length}`}
          </button>
        </p>
      )}
    </div>
  );
}

function TimelinePanel({ appid }: { appid: number }) {
  const tl = useAsync(async () => {
    const summary = (await loadTimelineIndex()).find((g) => g.appid === appid);
    return summary ? { summary, detail: await loadTimeline(appid) } : null;
  }, [appid]);
  const series: Series[] = useMemo(() => {
    if (!tl.data) return [];
    const { summary, detail } = tl.data;
    return [
      {
        name: summary.name,
        points: monthlySeries(detail, true),
        changes: detail.changes,
        firstMonth: detail.months[0]?.[0] ?? summary.first,
      },
    ];
  }, [tl.data]);

  if (tl.error) return <ErrorNote error={tl.error} />;
  if (tl.data === undefined) return null;
  if (tl.data === null) {
    return (
      <p className="note">
        No review history for this game: monthly timelines cover the 5,000 most-reviewed games.
      </p>
    );
  }
  const s = tl.data.summary;
  return (
    <div className="panel">
      <div className="panel-header">
        <h2>Review history</h2>
        <Link to={`/timelines?games=${appid}`}>Turning points and announcements →</Link>
      </div>
      <TimelineChart series={series} align="calendar" />
      <p className="chart-note muted">
        Positive share by month (3-month window). Launch {fmtPct(s.launch, 0)}, last 12 months {fmtPct(s.recent, 0)}
        {s.drift != null ? ` (${fmtPp(s.drift)})` : ""}. Dots mark turning points.
      </p>
    </div>
  );
}

function SimilarPanel({ game }: { game: GameDetail }) {
  const similar = useAsync(() => similarGames(game.appid, game.dev_id), [game.appid]);
  if (similar.error) return <ErrorNote error={similar.error} />;
  if (!similar.data?.length) return null;
  return (
    <div className="panel">
      <h2>Tagged most like it</h2>
      <p className="muted small">
        The most-reviewed of the 40 games from other developers whose tags are closest to its own (top tags count more).
      </p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Game</th>
              <th className="num">Shared tags</th>
              <th className="num">Reviews</th>
              <th className="num">Score</th>
              <th className="num">vs predicted</th>
            </tr>
          </thead>
          <tbody>
            {similar.data.map((s) => (
              <tr key={s.appid}>
                <td className="wrap">
                  <Link to={gameHref(s.appid)}>{s.name}</Link>{" "}
                  {s.year != null && <span className="muted">({s.year})</span>}
                </td>
                <td className="num">
                  {s.shared} of {game.tagids.length}
                </td>
                <td className="num">{fmtInt(s.review_count)}</td>
                <td className="num">{fmtPct(s.score, 0)}</td>
                <td className={`num tone-${s.resid > 3 ? "positive" : s.resid < -3 ? "negative" : "neutral"}`}>
                  {fmtPp(s.resid)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Stat({ label, value, hint, tone }: { label: string; value: string; hint?: string; tone?: string }) {
  return (
    <div className={`card${tone ? ` tone-${tone}` : ""}`}>
      <div className="card-label">{label}</div>
      <div className="card-value">{value}</div>
      {hint && <div className="card-hint">{hint}</div>}
    </div>
  );
}
