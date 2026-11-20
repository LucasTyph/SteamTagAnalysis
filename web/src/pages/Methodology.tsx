import { Link } from "react-router-dom";
import { ErrorNote, Loading } from "../components/Loading";
import { REPO_URL, loadFindings } from "../data/findings";
import { loadMeta } from "../data/queries";
import { fmtInt } from "../lib/format";
import { useAsync } from "../lib/hooks";
import { usePageMeta } from "../lib/pageMeta";

const SECTIONS = [
  ["data", "Data"],
  ["scores", "Scores"],
  ["tags", "Tags"],
  ["effects", "Mix effects"],
  ["timelines", "Timelines"],
  ["limits", "Limitations"],
  ["reproduce", "Reproduce it"],
] as const;

export function Methodology() {
  usePageMeta("Methodology", "How the Steam data was collected, what each number means, and where it can mislead.");
  const data = useAsync(() => Promise.all([loadMeta(), loadFindings()]), []);
  if (data.error) return <ErrorNote error={data.error} />;
  if (!data.data) return <Loading label="Loading…" />;
  const [meta, findings] = data.data;
  const a = meta.analysis as Record<string, number>;
  const b = meta.build as Record<string, number | string>;
  const alpha = Number(a.prior_alpha);
  const beta = Number(a.prior_beta);
  const priorMean = (100 * alpha) / (alpha + beta);
  const strength = alpha + beta;
  const built = String(b.data_as_of ?? b.built_at ?? "").slice(0, 10);
  const launchDates = Number(b.launch_dates ?? 0);
  const launchCorrected = Number(b.launch_corrected ?? 0);

  return (
    <section className="page prose">
      <header className="page-header">
        <h1>Methodology</h1>
        <p className="lede">
          How the data was collected, what each number means, and where it can mislead. The full code (pipeline, tests,
          notebooks) is on <a href={REPO_URL}>GitHub</a>.
        </p>
      </header>

      <nav className="toc" aria-label="On this page">
        {SECTIONS.map(([id, label]) => (
          <a
            key={id}
            href={`#${id}`}
            onClick={(e) => {
              // Hash routing owns the URL fragment, so scroll instead of navigating.
              e.preventDefault();
              document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
            }}
          >
            {label}
          </a>
        ))}
      </nav>

      <h2 id="data">Data</h2>
      <p>
        All data comes from public Steam store endpoints. This copy was collected on {built || "the build date"}; a
        scheduled job re-collects everything and rebuilds the site at the start of each month:
      </p>
      <ul>
        <li>
          <strong>App list</strong> (Steam Web API): every app Steam lists as a game, about 200,000.
        </li>
        <li>
          <strong>Store details</strong> (<code>IStoreBrowseService/GetItems</code>, 200 games per request): the top 20
          user tags with vote counts, review totals and positive share, release dates, price, and developer.
        </li>
        <li>
          <strong>Review history</strong> (<code>appreviewhistogram</code>): monthly positive and negative review counts
          over each game's life, for the 5,000 most-reviewed games (about 2,300 reviews or more).
        </li>
        <li>
          <strong>Announcements</strong> (<code>ISteamNews</code>): developer news posts for the same 5,000 games.
        </li>
      </ul>
      <p>
        The tag analysis covers the <strong>{fmtInt(meta.counts.games)}</strong> games with at least {String(b.min_reviews)}{" "}
        reviews, from {fmtInt(meta.counts.developers)} developers. The fetcher is rate-limited, resumable and stores every
        raw response, so the analysis can be re-run without re-downloading.
      </p>

      <h2 id="scores">Scores</h2>
      <p>
        A game's raw positive share is noisy when it has few reviews: 20 out of 20 isn't really better than 950 out of
        1,000. Each game's <strong>score</strong> is therefore an empirical-Bayes estimate. A beta distribution is fitted
        to all games (mean {priorMean.toFixed(1)}%, worth about {strength.toFixed(0)} reviews), and each game's score is
        its positive share pulled toward that mean in proportion to how little evidence it has. Games with thousands of
        reviews keep their own share; a 20-review game moves about a quarter of the way to the average.
      </p>
      <p>
        Positive share uses Steam's own filtered count, which excludes reviews Steam flagged as off-topic (review
        bombs) since 2019. Steam reports it as a whole percentage, so per-game counts are rounded.
      </p>

      <h2 id="tags">Tags</h2>
      <p>
        Steam shows up to 20 player-voted tags per game. Only a game's <strong>top {String(b.tag_max_rank)}</strong>{" "}
        tags by votes count as describing it. A vote-share cutoff was tested and dropped: shares fall so slowly that
        even the 20th tag typically has a third of the top tag's votes, so the cutoff let almost every tag through.
        Software tags that leak onto games ({findings.excluded_tags.slice(0, 4).join(", ")}, …) are left out.
      </p>

      <h2 id="effects">Mix effects</h2>
      <p>
        To ask whether a tag <em>mix</em> does better than its parts, a baseline model predicts each game's score from
        its tags alone: ridge regression on the logit of the score, with one term per tag plus controls for release
        year, price band, popularity band and early access. It explains about {(100 * Number(a.r2)).toFixed(0)}% of the
        variance ({(100 * Number(a.cv_r2)).toFixed(0)}% on held-out data, so it isn't overfitting).
      </p>
      <p>
        A mix's <strong>effect</strong> is how far its games score above or below that prediction, in percentage points.
        Five safeguards keep it honest:
      </p>
      <ul>
        <li>
          <strong>Each mix gets its own baseline.</strong> With one shared baseline, a mix's own games help fit its
          tags' coefficients, so part of a real interaction gets credited to the tags and the effect reads low. Every
          pair and triple is instead compared with the model refitted <em>without its own games</em> (ridge regression
          has an exact shortcut for this, so all {fmtInt(meta.counts.pairs + meta.counts.triples)} mixes take about two
          minutes). Each analysis checks this by planting a known +{Number(a.planted_pp).toFixed(1)} point interaction
          on {String(a.n)} random pairs: it recovers {(100 * Number(a.recovery_median)).toFixed(0)}% of it (the shared
          baseline: {(100 * Number(a.shared_recovery_median)).toFixed(0)}%). On the real data most effects move by a few
          percent; the biggest corrections are for mixes that make up a large share of one of their tags' games.
        </li>
        <li>
          <strong>Developers count once.</strong> Games from the same developer aren't independent; one studio once
          released 30 near-identical games that dominated the rankings. Each developer's games are averaged first, and
          confidence intervals use developers as the unit. A mix needs at least {String(a.min_devs)} developers and{" "}
          {String(a.min_support)} games.
        </li>
        <li>
          <strong>Look-alike developers count as one.</strong> Clone operations release near-identical games under a new
          developer name each time. Developers are grouped when two of their games have near-identical tags, came out
          close together, and share a publisher (small games only), a near-identical title (&ldquo;Hentai Girl
          Karen&rdquo; / &ldquo;Hentai Girl Linda&rdquo;), or are both shells named after the game (a wave of Chinese
          &ldquo;传奇&rdquo; MMO clones). That merged {fmtInt(Number(b.grouped_devs))} developer accounts into{" "}
          {fmtInt(Number(b.studio_groups))} groups. It errs toward merging: a wrong merge only widens a confidence
          interval, while a missed clone series can fake a hidden gem.
        </li>
        <li>
          <strong>Multiple testing.</strong> With tens of thousands of mixes, some look great by chance. Hidden Gems only
          lists mixes that pass a Benjamini–Hochberg false-discovery correction (q &lt; 0.1), ranked by the end of the 90%
          confidence interval closest to zero.
        </li>
        <li>
          <strong>Near-synonyms.</strong> Pairs that almost always appear together (Roguelike + Roguelite, Nudity + Sexual
          Content) restate one tag, so they're excluded from the rankings.
        </li>
      </ul>
      <p>
        The <Link to="/explore">Tag Explorer</Link> shows these precomputed effects for pairs and triples. With filters
        or a fourth tag it computes effects live in the browser against the shared baseline, which reads slightly low.
        Read an effect together with the mix's actual score: a mix can beat its prediction and still score below
        average if it rescues a weak genre.
      </p>

      <h2 id="timelines">Timelines</h2>
      <ul>
        <li>
          <strong>Launch</strong> score: the first 3 months of reviews, extended up to 6 until there are 50 reviews. Games
          older than Steam's review system (October 2010) get none.
        </li>
        <li>
          <strong>Turning points</strong>: change-point detection (PELT) on the monthly positive share, with a penalty
          scaled to each game's own month-to-month noise. Only shifts of 5 points or more are kept, at most 6 per game.
        </li>
        <li>
          <strong>Nearest announcement</strong>: the closest developer post titled like an update or launch within ±45
          days. This is proximity, not cause. Some of the biggest drops were external events (pricing, account
          requirements, publisher controversies) that happened to land near a routine patch.
        </li>
      </ul>

      <h2 id="limits">Limitations</h2>
      <ul>
        <li>
          <strong>Survivorship:</strong> delisted games are missing, which flatters older years.
        </li>
        <li>
          <strong>Tags are today's tags,</strong> not the ones a game had at launch.
        </li>
        <li>
          <strong>Release dates:</strong> for many games that left early access, Steam only returns the 1.0 date (Rust
          shows 2018, not 2013). A game's launch is therefore its first review when that is more than a month earlier.{" "}
          {launchDates >= 0.995 * meta.counts.games ? (
            <>
              That moved {fmtInt(launchCorrected)} of {fmtInt(meta.counts.games)} launches earlier.
            </>
          ) : (
            <>
              First-review dates are being collected a slice a day for every game: {fmtInt(launchDates)} of{" "}
              {fmtInt(meta.counts.games)} so far, which moved {fmtInt(launchCorrected)} launches earlier. Games still
              without one use Steam's date.
            </>
          )}
        </li>
        <li>
          <strong>Developer grouping is a heuristic:</strong> a clone series that varies its titles and tags can still
          count as several developers, and a few unrelated developers with near-identical small games get merged.
        </li>
        <li>
          <strong>Correlation only:</strong> a mix that scores well isn't a recipe; the games in it may share other
          qualities the tags don't capture.
        </li>
        <li>
          <strong>Timelines cover the 5,000 most-reviewed games,</strong> which skews toward big, long-running titles. Smaller games have quiet months below the 20-review minimum, so their charts have gaps.
        </li>
      </ul>

      <h2 id="reproduce">Reproduce it</h2>
      <pre>
        <code>{`pip install -e ".[analysis,dev]"
stp fetch all            # app list, tags, reviews, developers (resumable)
stp fetch timelines --top 5000   # review history + news
stp build && stp analyze && stp export`}</code>
      </pre>
      <p>
        Every fetch can be stopped at any time and resumed with the same command. See the{" "}
        <a href={`${REPO_URL}#readme`}>README</a> and the notebooks for the exploratory checks behind each decision. Back to{" "}
        <Link to="/findings">the findings</Link>.
      </p>
    </section>
  );
}
