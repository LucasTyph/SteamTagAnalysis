import { Link } from "react-router-dom";
import { REPO_URL, loadFindings } from "../data/findings";
import { fmtMonth } from "../data/timelines";
import { fmtPct, fmtPp } from "../lib/format";
import { useAsync } from "../lib/hooks";

const TOOLS = [
  {
    to: "/explore",
    title: "Tag Explorer",
    text: "Pick any mix of Steam tags and see how its games are reviewed, live in your browser.",
  },
  {
    to: "/gems",
    title: "Hidden Gems",
    text: "Tag mixes that beat (or miss) what their parts predict, with confidence intervals.",
  },
  {
    to: "/timelines",
    title: "Review Timelines",
    text: "Month-by-month reception of the 5,000 most-reviewed games, with turning points and patches.",
  },
  {
    to: "/releases",
    title: "New Releases",
    text: "Every new Steam game followed day by day for its first year, updated daily.",
  },
  {
    to: "/findings",
    title: "Findings",
    text: "Eight things the data says, from review bombs to which genres age well.",
  },
];

export function Home() {
  const f = useAsync(loadFindings, []);
  const d = f.data;
  const best = d?.pairs_best.find((p) => p.score >= 80) ?? d?.pairs_best[0];
  const worst = d?.pairs_worst[0];
  const comeback = d?.comebacks?.find((c) => c.name === "No Man's Sky") ?? d?.comebacks?.[0];

  return (
    <section className="page home">
      <div className="hero">
        <h1>What makes a Steam game land?</h1>
        <p className="lede">
          An analysis of 200,000 Steam apps, 60,000 reviewed games and 120 million reviews: which genre mixes beat
          expectations, and how a game's reception changes after launch.
        </p>
        <div className="hero-actions">
          <Link className="button primary" to="/explore">
            Explore tag mixes
          </Link>
          <Link className="button" to="/findings">
            Read the findings
          </Link>
        </div>
      </div>

      {d && best && worst && comeback && (
        <div className="headline-cards">
          <Link className="headline tone-positive" to={`/explore?tags=${encodeURIComponent(best.tags.join(","))}`}>
            <span className="headline-kicker">Beats its parts</span>
            <span className="headline-value">{fmtPp(best.effect)}</span>
            <span className="headline-text">
              <strong>{best.tags.join(" + ")}</strong> games score {fmtPct(best.score)}, above the{" "}
              {fmtPct(best.predicted)} their tags predict ({best.n_devs} developers).
            </span>
          </Link>
          <Link className="headline tone-negative" to={`/explore?tags=${encodeURIComponent(worst.tags.join(","))}`}>
            <span className="headline-kicker">Misses its parts</span>
            <span className="headline-value">{fmtPp(worst.effect)}</span>
            <span className="headline-text">
              <strong>{worst.tags.join(" + ")}</strong> games score {fmtPct(worst.score)} against a predicted{" "}
              {fmtPct(worst.predicted)}.
            </span>
          </Link>
          <Link className="headline" to={`/timelines?games=${comeback.appid}`}>
            <span className="headline-kicker">Comeback</span>
            <span className="headline-value">
              {fmtPct(comeback.trough, 0)} → {fmtPct(comeback.recent, 0)}
            </span>
            <span className="headline-text">
              <strong>{comeback.name}</strong> fell to {fmtPct(comeback.trough, 0)} positive in {fmtMonth(comeback.trough_month)} and recovered to {fmtPct(comeback.recent, 0)} over the last 12 months.
            </span>
          </Link>
        </div>
      )}

      <div className="tool-grid">
        {TOOLS.map((t) => (
          <Link key={t.to} className="tool" to={t.to}>
            <h2>{t.title} →</h2>
            <p className="muted">{t.text}</p>
          </Link>
        ))}
      </div>

      <div className="panel how">
        <h2>How it's built</h2>
        <ol className="steps">
          <li>
            <strong>Collect.</strong> A resumable Python fetcher pulls tags, reviews, developers and review history from
            Steam's store endpoints, rate-limited, and pausable at any point.
          </li>
          <li>
            <strong>Model.</strong> Scores are adjusted for small samples, a ridge model predicts each game from its tags,
            and mix effects are measured per developer with false-discovery control.
          </li>
          <li>
            <strong>Publish.</strong> The results ship as about 15 MB of Parquet and JSON, loaded only as needed. This
            site queries them in your browser with DuckDB-WASM. No server.
          </li>
        </ol>
        <p className="muted small">
          <Link to="/methodology">Methodology and limitations</Link> · <a href={REPO_URL}>Source on GitHub</a>
        </p>
      </div>
    </section>
  );
}
