import * as Plot from "@observablehq/plot";
import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ErrorNote, Loading } from "../components/Loading";
import {
  type CurvePoint,
  type Mover,
  type ReleaseGame,
  type ReleasesData,
  type Settle,
  cumulativeSeries,
  loadGameDays,
  loadReleases,
} from "../data/releases";
import { NEG, POS, SERIES_COLORS } from "../lib/colors";
import { fmtInt, fmtPct, fmtPp, steamUrl } from "../lib/format";
import { useAsync } from "../lib/hooks";

const fmtDate = (iso: string | null | undefined) =>
  iso
    ? new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
        year: "numeric",
        timeZone: "UTC",
      })
    : "–";

export function Releases() {
  const data = useAsync(loadReleases, []);
  if (data.error) return <ErrorNote error={data.error} />;
  if (data.loading) return <Loading label="Loading release tracking…" />;
  if (!data.data) {
    return (
      <section className="page">
        <h1>New Releases</h1>
        <p className="note">
          No tracking data in this build. It is generated at deploy time from the <code>tracking-data</code> branch; locally,
          run <code>stp track export</code>.
        </p>
      </section>
    );
  }
  return <ReleasesView d={data.data} />;
}

function ReleasesView({ d }: { d: ReleasesData }) {
  const [params, setParams] = useSearchParams();
  const selected = Number(params.get("game")) || null;
  const { meta, aggregates: agg } = d;
  const perDay = meta.releases_per_day.filter(([day]) => !meta.data_through || day < meta.data_through);
  const recent = perDay.slice(-14);
  const avg = recent.length ? recent.reduce((s, [, n]) => s + n, 0) / recent.length : 0;
  const daysTracked = meta.tracking_since && meta.data_through
    ? Math.round((Date.parse(meta.data_through) - Date.parse(meta.tracking_since)) / 86400000) + 1
    : 0;
  const open = (appid: number) => {
    const p = new URLSearchParams(params);
    p.set("game", String(appid));
    setParams(p);
  };

  return (
    <section className="page releases">
      <header className="page-header">
        <h1>New Releases</h1>
        <p className="lede">
          Every game released on Steam, followed day by day for its first year: how many reviews it collects and how its
          positive share moves. Updated daily since {fmtDate(meta.tracking_since)}; games released up to 30 days
          before that have their history from day one.
        </p>
      </header>

      <div className="cards">
        <Card label="Games tracked" value={fmtInt(meta.tracked)} hint={`${fmtInt(meta.with_reviews)} with reviews`} />
        <Card label="Releases per day" value={avg ? avg.toFixed(0) : "–"} hint="average, last 14 days" />
        <Card label="Days of tracking" value={fmtInt(daysTracked)} hint={`data through ${fmtDate(meta.data_through)}`} />
        <Card label="Listed below" value={fmtInt(meta.listed_games)} hint={`games with ${meta.min_reviews_listed}+ reviews`} />
      </div>

      {selected && <GameDetail appid={selected} games={d.games} onClose={() => {
        const p = new URLSearchParams(params);
        p.delete("game");
        setParams(p);
      }} />}

      <div className="panel">
        <h2>Releases per day</h2>
        <p className="muted small">Games that came out each day, by Steam's release date (the current day is left out until it ends).</p>
        <PerDayChart data={perDay.slice(-60)} />
      </div>

      <div className="panel">
        <h2>Does the score settle after the first days?</h2>
        <p className="muted small">
          Change in each game's cumulative positive share between two points after release, for games with at least 20
          reviews by the first point. Sections fill in as tracking continues.
        </p>
        <div className="settle-grid">
          {agg.settle.map((s) => (
            <SettleBlock key={`${s.from_day}-${s.to_day}`} s={s} />
          ))}
        </div>
      </div>

      <div className="panel">
        <h2>How the positive share evolves</h2>
        <p className="muted small">
          Median cumulative positive share by day since release, among games with 20+ reviews by that day (band: middle
          half of games). Early-access and full launches are shown separately once each has enough games.
        </p>
        <CurveChart
          series={[
            { name: "All games", points: agg.curve_all },
            { name: "Early access", points: agg.curve_early_access },
            { name: "Full launch", points: agg.curve_full_launch },
          ].filter((s) => s.points.length > 0)}
        />
      </div>

      <div className="panel">
        <h2>Which genres collect reviews fastest?</h2>
        {agg.speed_by_tag.length === 0 ? (
          <p className="muted">Not enough tagged games yet; this fills in after the next daily runs.</p>
        ) : (
          <>
            <p className="muted small">
              Median reviews in the first 7 days, by each game's most-voted tag (tags with 15+ games). Most new releases get
              very few reviews, so the median is often small; the share reaching 10 reviews is shown alongside.
            </p>
            <ul className="bar-list">
              {agg.speed_by_tag.slice(0, 15).map((t) => {
                const max = agg.speed_by_tag[0].median || 1;
                return (
                  <li key={t.tag}>
                    <span className="bar-label">{t.tag}</span>
                    <span className="bar-track">
                      <span className="bar" style={{ left: 0, width: `${Math.max(1, (100 * t.median) / max)}%` }} />
                    </span>
                    <span className="bar-value">{t.median}</span>
                    <span className="bar-note muted">
                      {t.n} games · {fmtPct(t.pct_10plus, 0)} reached 10 reviews
                    </span>
                  </li>
                );
              })}
            </ul>
          </>
        )}
      </div>

      {(agg.risers.length > 0 || agg.fallers.length > 0) && (
        <div className="panel">
          <h2>Biggest moves since week one</h2>
          <p className="muted small">Positive share now compared with after 7 days (games with 50+ reviews, 20+ in week one).</p>
          <div className="two-col">
            <MoverTable title="Rose" rows={agg.risers.filter((m) => m.change > 0)} onOpen={open} />
            <MoverTable title="Fell" rows={agg.fallers.filter((m) => m.change < 0)} onOpen={open} />
          </div>
        </div>
      )}

      <GameBrowser games={d.games} onOpen={open} />
    </section>
  );
}

function Card({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="card">
      <div className="card-label">{label}</div>
      <div className="card-value">{value}</div>
      {hint && <div className="card-hint">{hint}</div>}
    </div>
  );
}

function usePlot(build: (width: number) => Element | null, deps: unknown[]) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const node = build(el.clientWidth || 700);
    if (!node) return;
    el.replaceChildren(node);
    return () => node.remove();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return ref;
}

function PerDayChart({ data }: { data: [string, number][] }) {
  // Each bar spans one UTC day; tooltips anchor to the bar's centre (`mid`) so the
  // popup sits on the bar and the hover zone matches the bar's own width.
  const rows = data.map(([day, n]) => {
    const start = Date.parse(`${day}T00:00:00Z`);
    return { day, start: new Date(start), end: new Date(start + 86400000), mid: new Date(start + 43200000), n };
  });
  const ref = usePlot(
    (width) =>
      Plot.plot({
        width,
        height: 200,
        marginLeft: 40,
        x: { type: "utc", label: null },
        y: { label: "↑ Games", grid: true },
        marks: [
          Plot.rectY(rows, { x1: "start", x2: "end", y: "n", fill: SERIES_COLORS[0], inset: 0.5 }),
          Plot.ruleY([0]),
          Plot.tip(rows, Plot.pointerX({ x: "mid", y: "n", title: (r) => `${fmtDate(r.day)}: ${r.n} releases` })),
        ],
        style: { background: "transparent", fontSize: "12px" },
      }),
    [data],
  );
  return <div className="plot" ref={ref} role="img" aria-label="Steam releases per day" />;
}

/** 2-point bins from −25 to +25 (values beyond are clamped into the end bins). */
function histogram(values: number[]) {
  const bins = Array.from({ length: 25 }, (_, i) => ({ x1: -25 + 2 * i, x2: -23 + 2 * i, n: 0 }));
  for (const v of values) {
    const i = Math.min(24, Math.max(0, Math.floor((v + 25) / 2)));
    bins[i].n += 1;
  }
  return bins;
}

function SettleBlock({ s }: { s: Settle }) {
  const ready = s.median != null && s.changes;
  const ref = usePlot(
    (width) =>
      ready
        ? Plot.plot({
            width,
            height: 160,
            marginLeft: 36,
            x: { label: "Change (points) →", domain: [-25, 25] },
            y: { label: "↑ Games", grid: true },
            marks: [
              Plot.rectY(histogram(s.changes!), {
                x1: "x1",
                x2: "x2",
                y: "n",
                fill: SERIES_COLORS[0],
                inset: 0.5,
              }),
              Plot.ruleX([0], { stroke: "currentColor", strokeOpacity: 0.5 }),
              Plot.ruleY([0]),
              Plot.tip(
                histogram(s.changes!),
                Plot.pointerX({
                  x: (b) => (b.x1 + b.x2) / 2,
                  y: "n",
                  title: (b) => `${b.x1 > 0 ? "+" : ""}${b.x1} to ${b.x2 > 0 ? "+" : ""}${b.x2} points: ${b.n} games`,
                }),
              ),
            ],
            style: { background: "transparent", fontSize: "11px" },
          })
        : null,
    [s],
  );
  return (
    <div className="settle">
      <h3 className="small-heading">
        Day {s.from_day} → day {s.to_day}
      </h3>
      {ready ? (
        <>
          <p className="settle-stat">
            <strong>{fmtPp(s.median)}</strong> median ·{" "}
            <span className="tone-negative">{fmtPct(s.pct_down_5, 0)} fell 5+</span> ·{" "}
            <span className="tone-positive">{fmtPct(s.pct_up_5, 0)} rose 5+</span>
          </p>
          <div className="plot" ref={ref} role="img" aria-label={`Distribution of changes from day ${s.from_day} to day ${s.to_day}`} />
          <p className="muted small">{fmtInt(s.n)} games</p>
        </>
      ) : (
        <p className="muted small">
          Not enough games observed through day {s.to_day} yet ({s.n} so far). This fills in as tracking continues.
        </p>
      )}
    </div>
  );
}

function CurveChart({ series }: { series: { name: string; points: CurvePoint[] }[] }) {
  const ref = usePlot(
    (width) => {
      if (!series.length) return null;
      const rows = series.flatMap((s) =>
        s.points.map(([day, n, p25, median, p75]) => ({ series: s.name, day, n, p25, median, p75 })),
      );
      const first = rows.filter((r) => r.series === series[0].name);
      return Plot.plot({
        width,
        height: 280,
        marginLeft: 40,
        x: { label: "Days since release →", grid: true },
        y: { label: "↑ Cumulative % positive", grid: true, domain: [40, 100] },
        color: series.length > 1 ? { domain: series.map((s) => s.name), range: SERIES_COLORS, legend: true } : undefined,
        marks: [
          Plot.areaY(first, { x: "day", y1: "p25", y2: "p75", fill: SERIES_COLORS[0], fillOpacity: 0.15 }),
          Plot.line(rows, { x: "day", y: "median", stroke: series.length > 1 ? "series" : SERIES_COLORS[0], strokeWidth: 2 }),
          Plot.tip(
            rows,
            Plot.pointerX({
              x: "day",
              y: "median",
              title: (r) => `${r.series}, day ${r.day}\nmedian ${r.median}% (middle half ${r.p25}–${r.p75}%)\n${r.n} games`,
            }),
          ),
        ],
        style: { background: "transparent", fontSize: "12px" },
      });
    },
    [series],
  );
  if (!series.length) return <p className="muted">Not enough games with 20+ reviews yet.</p>;
  return <div className="plot" ref={ref} role="img" aria-label="Median cumulative positive share by day since release" />;
}

function MoverTable({ title, rows, onOpen }: { title: string; rows: Mover[]; onOpen: (appid: number) => void }) {
  return (
    <div>
      <h3 className="small-heading">{title}</h3>
      {rows.length === 0 ? (
        <p className="muted small">None yet.</p>
      ) : (
        <ul className="plain-list">
          {rows.map((m) => (
            <li key={m.appid}>
              <button type="button" className="link" onClick={() => onOpen(m.appid)}>
                {m.name}
              </button>
              <span className="muted">
                {fmtPct(m.d7_pct, 0)} → {fmtPct(m.pct, 0)} ({fmtPp(m.change, 0)})
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

type Sort = "reviews" | "newest" | "best" | "worst";

function GameBrowser({ games, onOpen }: { games: ReleaseGame[]; onOpen: (appid: number) => void }) {
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<Sort>("reviews");
  const [limit, setLimit] = useState(50);
  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const list = needle
      ? games.filter((g) => g.name.toLowerCase().includes(needle) || g.tag?.toLowerCase().includes(needle))
      : [...games];
    const withPct = (g: ReleaseGame) => (g.reviews >= 20 && g.pct != null ? g.pct : null);
    return list.sort((a, b) => {
      if (sort === "newest") return b.release.localeCompare(a.release) || b.reviews - a.reviews;
      if (sort === "best") return (withPct(b) ?? -1) - (withPct(a) ?? -1);
      if (sort === "worst") return (withPct(a) ?? 101) - (withPct(b) ?? 101);
      return b.reviews - a.reviews;
    });
  }, [games, q, sort]);

  return (
    <div className="panel">
      <div className="panel-header">
        <h2>Browse tracked games</h2>
        <div className="segmented" role="tablist" aria-label="Sort games">
          {(
            [
              ["reviews", "Most reviewed"],
              ["newest", "Newest"],
              ["best", "Best rated"],
              ["worst", "Worst rated"],
            ] as [Sort, string][]
          ).map(([k, label]) => (
            <button key={k} type="button" role="tab" aria-selected={sort === k} onClick={() => setSort(k)}>
              {label}
            </button>
          ))}
        </div>
      </div>
      <input
        className="search"
        type="search"
        placeholder="Search by name or tag…"
        value={q}
        onChange={(e) => {
          setQ(e.target.value);
          setLimit(50);
        }}
        aria-label="Search tracked games"
      />
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Game</th>
              <th>Tag</th>
              <th className="num">Released</th>
              <th className="num">Reviews</th>
              <th className="num">Positive</th>
              <th className="num">After 7 days</th>
            </tr>
          </thead>
          <tbody>
            {rows.slice(0, limit).map((g) => (
              <tr key={g.appid}>
                <td>
                  <button type="button" className="link" onClick={() => onOpen(g.appid)}>
                    {g.name}
                  </button>
                  {g.ea && <span className="badge">Early access</span>}
                </td>
                <td className="muted">{g.tag ?? "–"}</td>
                <td className="num">{fmtDate(g.release)}</td>
                <td className="num">{fmtInt(g.reviews)}</td>
                <td className="num">{g.pct != null ? `${g.pct}%` : "–"}</td>
                <td className="num muted">
                  {g.d7_pct != null ? `${g.d7_pct.toFixed(0)}% of ${fmtInt(g.d7_reviews)}` : "–"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted small">
        Showing {fmtInt(Math.min(limit, rows.length))} of {fmtInt(rows.length)}.{" "}
        {limit < rows.length && (
          <button type="button" className="link" onClick={() => setLimit((l) => l + 100)}>
            Show more
          </button>
        )}
      </p>
    </div>
  );
}

function GameDetail({ appid, games, onClose }: { appid: number; games: ReleaseGame[]; onClose: () => void }) {
  const game = games.find((g) => g.appid === appid);
  const days = useAsync(() => loadGameDays(appid), [appid]);
  const panelRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    // Block body: in newer browsers scrollIntoView returns a Promise, which React would
    // otherwise treat as a cleanup function.
    panelRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [appid]);

  const series = useMemo(() => {
    if (!days.data) return [];
    const last = Math.max(0, ...days.data.days.map(([d]) => d));
    return cumulativeSeries(days.data, last);
  }, [days.data]);
  // Shared x range so the two charts line up: bars span [day, day + 1).
  const xDomain: [number, number] = [0, series.length];

  const volRef = usePlot(
    (width) =>
      series.length
        ? Plot.plot({
            width,
            height: 160,
            marginLeft: 40,
            x: { label: "Days since release →", domain: xDomain },
            y: { label: "↑ Reviews per day", grid: true },
            color: { domain: ["positive", "negative"], range: [POS, NEG], legend: true },
            marks: [
              Plot.rectY(
                series.flatMap((s) => [
                  { day: s.day, n: s.up, kind: "positive" },
                  { day: s.day, n: s.down, kind: "negative" },
                ]),
                { x1: "day", x2: (r) => r.day + 1, y: "n", fill: "kind", inset: 0.3 },
              ),
              Plot.ruleY([0]),
              // Bars span [day, day + 1): anchor tooltips at the centre of each bar.
              Plot.tip(
                series,
                Plot.pointerX({
                  x: (s) => s.day + 0.5,
                  y: (s) => s.up + s.down,
                  title: (s) => `Day ${s.day}: ${s.up} positive, ${s.down} negative`,
                }),
              ),
            ],
            style: { background: "transparent", fontSize: "11px" },
          })
        : null,
    [series],
  );
  const pctRef = usePlot(
    (width) =>
      series.some((s) => s.pct != null)
        ? Plot.plot({
            width,
            height: 200,
            marginLeft: 40,
            x: { label: "Days since release →", domain: xDomain },
            y: { label: "↑ Cumulative % positive", domain: [0, 100], grid: true },
            marks: [
              Plot.line(series, { x: (s) => s.day + 0.5, y: (s) => s.pct ?? Number.NaN, stroke: SERIES_COLORS[0], strokeWidth: 2 }),
              Plot.tip(
                series.filter((s) => s.pct != null),
                Plot.pointerX({ x: (s) => s.day + 0.5, y: "pct", title: (s) => `Day ${s.day}: ${s.pct!.toFixed(1)}% positive of ${s.cumN} reviews` }),
              ),
            ],
            style: { background: "transparent", fontSize: "11px" },
          })
        : null,
    [series],
  );

  return (
    <div className="panel game-detail" ref={panelRef}>
      <div className="panel-header">
        <h2>
          {game ? (
            <a href={steamUrl(appid)} target="_blank" rel="noreferrer">
              {game.name}
            </a>
          ) : (
            `App ${appid}`
          )}
        </h2>
        <button type="button" className="link" onClick={onClose}>
          Close
        </button>
      </div>
      {game && (
        <p className="muted">
          Released {fmtDate(game.release)}
          {game.ea ? " in early access" : ""}
          {game.tag ? ` · ${game.tag}` : ""} · {fmtInt(game.reviews)} reviews
          {game.pct != null ? `, ${game.pct}% positive` : ""}
          {!game.clean && " · has reviews dated before its listed release (likely an earlier early-access launch)"}
        </p>
      )}
      {days.loading && <Loading label="Loading daily reviews…" />}
      {days.data === null && !days.loading && <p className="muted">No daily history for this game yet.</p>}
      {series.length > 0 && (
        <>
          <div className="plot" ref={volRef} role="img" aria-label="Reviews per day since release" />
          <div className="plot" ref={pctRef} role="img" aria-label="Cumulative positive share since release" />
          <p className="muted small">Cumulative share is shown once the game has 10 reviews.</p>
        </>
      )}
    </div>
  );
}
