import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { GamePicker } from "../components/GamePicker";
import { ErrorNote, Loading } from "../components/Loading";
import { TagCurves } from "../components/TagCurves";
import { type Series, TimelineChart } from "../components/TimelineChart";
import {
  type TimelineDetail,
  type TimelineSummary,
  fmtMonth,
  loadTagCurves,
  loadTimeline,
  loadTimelineIndex,
  monthlySeries,
  monthsBetween,
} from "../data/timelines";
import { fmtInt, fmtPct, fmtPp, steamUrl } from "../lib/format";
import { useAsync } from "../lib/hooks";

const MAX_GAMES = 4;
const FEATURED = [
  "No Man's Sky",
  "Cyberpunk 2077",
  "Team Fortress 2",
  "HELLDIVERS™ 2",
  "Total War: WARHAMMER III",
  "Kerbal Space Program 2",
];

export function Timelines() {
  const index = useAsync(loadTimelineIndex, []);
  if (index.error) return <ErrorNote error={index.error} />;
  if (!index.data) return <Loading label="Loading timelines…" />;
  return <TimelinesView games={index.data} />;
}

function TimelinesView({ games }: { games: TimelineSummary[] }) {
  const [params, setParams] = useSearchParams();
  const byId = useMemo(() => new Map(games.map((g) => [g.appid, g])), [games]);
  const selected = useMemo(
    () =>
      (params.get("games") ?? "")
        .split(",")
        .map((s) => byId.get(Number(s)))
        .filter((g): g is TimelineSummary => !!g)
        .slice(0, MAX_GAMES),
    [params, byId],
  );
  const align = params.get("align") === "launch" ? "launch" : "calendar";
  const smooth = params.get("smooth") !== "0";

  const update = (next: { games?: TimelineSummary[]; align?: string; smooth?: boolean }) => {
    const p = new URLSearchParams();
    const g = next.games ?? selected;
    if (g.length) p.set("games", g.map((x) => x.appid).join(","));
    const a = next.align ?? align;
    if (a === "launch") p.set("align", "launch");
    if (!(next.smooth ?? smooth)) p.set("smooth", "0");
    setParams(p);
  };
  const open = (g: TimelineSummary) => update({ games: [g] });

  return (
    <section className="page">
      <header className="page-header">
        <h1>Review Timelines</h1>
        <p className="lede">
          How the share of positive reviews moved month by month for the {games.length.toLocaleString("en-US")}{" "}
          most-reviewed games on Steam. Turning points are detected automatically and shown next to the nearest
          update or launch announcement. Being close in time doesn't prove the update caused the change.
        </p>
      </header>

      <div className="controls">
        <GamePicker games={games} selected={selected} onChange={(g) => update({ games: g })} max={MAX_GAMES} />
        {selected.length > 0 && (
          <div className="filters">
            <div className="segmented" role="group" aria-label="Align">
              <button type="button" aria-pressed={align === "calendar"} onClick={() => update({ align: "calendar" })}>
                Calendar
              </button>
              <button type="button" aria-pressed={align === "launch"} onClick={() => update({ align: "launch" })}>
                Since launch
              </button>
            </div>
            <label>
              <input type="checkbox" checked={smooth} onChange={(e) => update({ smooth: e.target.checked })} /> Smooth
              (3-month window)
            </label>
          </div>
        )}
      </div>

      {selected.length === 0 ? (
        <Landing games={games} onOpen={open} />
      ) : (
        <GameView key={selected.map((g) => g.appid).join(",")} selected={selected} align={align} smooth={smooth} />
      )}
    </section>
  );
}

// --- selected games -------------------------------------------------------------

function GameView({
  selected,
  align,
  smooth,
}: {
  selected: TimelineSummary[];
  align: "calendar" | "launch";
  smooth: boolean;
}) {
  const details = useAsync(
    () => Promise.all(selected.map((g) => loadTimeline(g.appid))),
    [selected.map((g) => g.appid).join(",")],
  );
  const series: Series[] = useMemo(
    () =>
      (details.data ?? []).map((d: TimelineDetail, i) => ({
        name: selected[i].name,
        points: monthlySeries(d, smooth),
        changes: d.changes,
        firstMonth: d.months[0]?.[0] ?? selected[i].first,
      })),
    [details.data, selected, smooth],
  );

  if (details.error) return <ErrorNote error={details.error} />;
  if (!details.data) return <Loading label="Loading review history…" />;
  const single = selected.length === 1 ? selected[0] : null;

  return (
    <div>
      {single && <GameHeader game={single} />}
      <div className="panel">
        <TimelineChart series={series} align={align} />
        {single && (
          <p className="chart-note muted">
            Dots mark turning points: green where the score rose, red where it fell. Months with fewer than 20 reviews
            are left out.
          </p>
        )}
      </div>
      {single ? (
        <TurningPoints detail={details.data[0]} />
      ) : (
        <CompareTable games={selected} />
      )}
    </div>
  );
}

function GameHeader({ game }: { game: TimelineSummary }) {
  return (
    <>
      <div className="game-title">
        <h2>
          <a href={steamUrl(game.appid)} target="_blank" rel="noreferrer">
            {game.name}
          </a>
        </h2>
        <span className="muted">
          {game.developer ?? "Unknown developer"} · reviews since {fmtMonth(game.first)} · {fmtInt(game.reviews)}{" "}
          reviews
          {game.tags.length ? ` · ${game.tags.join(", ")}` : ""}
        </span>
      </div>
      <div className="cards">
        <Stat label="Launch" value={fmtPct(game.launch)} hint={game.launch == null ? "predates Steam reviews" : "first months"} />
        <Stat label="Last 12 months" value={fmtPct(game.recent)} />
        <Stat
          label="Change since launch"
          value={fmtPp(game.drift)}
          tone={game.drift == null ? undefined : game.drift > 3 ? "positive" : game.drift < -3 ? "negative" : undefined}
        />
        <Stat label="Lowest point" value={fmtPct(game.trough)} hint={fmtMonth(game.trough_month)} />
        <Stat label="All-time" value={fmtPct(game.overall)} />
      </div>
    </>
  );
}

function TurningPoints({ detail }: { detail: TimelineDetail }) {
  if (!detail.changes.length) {
    return <p className="note">No turning points: reviews stayed within a few points of their trend.</p>;
  }
  return (
    <div className="panel">
      <h2>Turning points</h2>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Month</th>
              <th className="num">Before</th>
              <th className="num">After</th>
              <th className="num">Change</th>
              <th>Nearest announcement (±45 days)</th>
            </tr>
          </thead>
          <tbody>
            {detail.changes.map((c) => (
              <tr key={c.month}>
                <td>{fmtMonth(c.month)}</td>
                <td className="num">{fmtPct(c.before, 0)}</td>
                <td className="num">{fmtPct(c.after, 0)}</td>
                <td className={`num tone-${c.after >= c.before ? "positive" : "negative"}`}>
                  {fmtPp(c.after - c.before, 0)}
                </td>
                <td className="wrap">
                  {c.news ? (
                    <>
                      <a href={c.news.url} target="_blank" rel="noreferrer">
                        {c.news.title}
                      </a>{" "}
                      <span className="muted">({c.news.date})</span>
                    </>
                  ) : (
                    <span className="muted">none. Possibly an external event or a review bomb</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function CompareTable({ games }: { games: TimelineSummary[] }) {
  return (
    <div className="panel">
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Game</th>
              <th className="num">Since</th>
              <th className="num">Launch</th>
              <th className="num">Lowest</th>
              <th className="num">Last 12 mo.</th>
              <th className="num">Change</th>
              <th className="num">Turning points</th>
            </tr>
          </thead>
          <tbody>
            {games.map((g) => (
              <tr key={g.appid}>
                <td>{g.name}</td>
                <td className="num">{fmtMonth(g.first)}</td>
                <td className="num">{fmtPct(g.launch)}</td>
                <td className="num">{fmtPct(g.trough)}</td>
                <td className="num">{fmtPct(g.recent)}</td>
                <td className="num">{fmtPp(g.drift)}</td>
                <td className="num">{g.changes}</td>
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

// --- landing: featured, leaderboards, tag curves -----------------------------------------

type Board = "comebacks" | "declines" | "improved" | "stable";

const BOARDS: Record<Board, { label: string; note: string; metric: (g: TimelineSummary) => number | null; fmt: (g: TimelineSummary) => string }> = {
  comebacks: {
    label: "Biggest comebacks",
    note: "Last 12 months compared with the lowest 3-month stretch after launch.",
    metric: (g) => g.recovery,
    fmt: (g) => `${fmtPct(g.trough, 0)} → ${fmtPct(g.recent, 0)}`,
  },
  declines: {
    label: "Biggest declines",
    note: "Last 12 months compared with the best 3-month stretch after launch.",
    metric: (g) => g.decline,
    fmt: (g) => `${fmtPct(g.peak, 0)} → ${fmtPct(g.recent, 0)}`,
  },
  improved: {
    label: "Most improved since launch",
    note: "Last 12 months compared with the launch window.",
    metric: (g) => g.drift,
    fmt: (g) => `${fmtPct(g.launch, 0)} → ${fmtPct(g.recent, 0)}`,
  },
  stable: {
    label: "Most consistent",
    note: "Lowest month-to-month variation, among games with at least 3 years of reviews.",
    metric: (g) => (g.volatility == null || monthsBetween(g.first, g.last) < 36 ? null : -g.volatility),
    fmt: (g) => `${fmtPct(g.overall, 0)} all-time · ±${g.volatility?.toFixed(1)} pp`,
  },
};

function Landing({ games, onOpen }: { games: TimelineSummary[]; onOpen: (g: TimelineSummary) => void }) {
  const [board, setBoard] = useState<Board>("comebacks");
  const featured = FEATURED.map((n) => games.find((g) => g.name === n)).filter((g): g is TimelineSummary => !!g);
  const ranked = useMemo(() => {
    const b = BOARDS[board];
    return games
      .filter((g) => b.metric(g) != null)
      .sort((x, y) => b.metric(y)! - b.metric(x)!)
      .slice(0, 15);
  }, [games, board]);

  return (
    <div>
      <div className="starters">
        <span className="muted">Try:</span>
        {featured.map((g) => (
          <button key={g.appid} type="button" className="chip" onClick={() => onOpen(g)}>
            {g.name}
          </button>
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
        <ol className="board">
          {ranked.map((g) => (
            <li key={g.appid}>
              <button type="button" className="link" onClick={() => onOpen(g)}>
                {g.name}
              </button>
              <span className="muted">{BOARDS[board].fmt(g)}</span>
            </li>
          ))}
        </ol>
      </div>

      <TagTrajectories />
    </div>
  );
}

const DEFAULT_CURVES = ["Free to Play", "Open World Survival Craft", "Strategy", "Souls-like"];

function TagTrajectories() {
  const curves = useAsync(loadTagCurves, []);
  const [picked, setPicked] = useState<string[] | null>(null);
  if (!curves.data) return curves.error ? <ErrorNote error={curves.error} /> : null;
  const all = [...curves.data].sort((a, b) => a.name.localeCompare(b.name));
  const defaults = DEFAULT_CURVES.filter((n) => all.some((c) => c.name === n));
  const active = picked ?? (defaults.length ? defaults : all.slice(0, 3).map((c) => c.name));
  const toggle = (name: string) =>
    setPicked(active.includes(name) ? active.filter((n) => n !== name) : [...active, name].slice(-4));

  return (
    <div className="panel">
      <h2>Do some genres age better?</h2>
      <p className="muted small">
        Average monthly score by months since first review, grouped by each game's most-voted tag (tags with at least
        8 games among the top 1,000). Pick up to 4; with one selected, the band shows the middle half of games.
      </p>
      <div className="starters">
        {all.map((c) => (
          <button
            key={c.tagid}
            type="button"
            className={`chip${active.includes(c.name) ? " chip-selected" : ""}`}
            aria-pressed={active.includes(c.name)}
            onClick={() => toggle(c.name)}
          >
            {c.name}
          </button>
        ))}
      </div>
      {active.length > 0 && <TagCurves curves={all.filter((c) => active.includes(c.name))} />}
      <p className="muted small">
        Want the tag mix behind these games? Try the <Link to="/explore">Tag Explorer</Link>.
      </p>
    </div>
  );
}
