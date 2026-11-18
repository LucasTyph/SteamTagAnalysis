# Steam Tag Analysis — Project Plan

Two interactive explorations of Steam data, published as a static website:

1. **Tag Mix Explorer**: every Steam game with 20+ reviews. Which combinations of user tags score above or below what their individual tags predict? The goal is to surface obscure, high-performing niches.
2. **Review Timelines**: the top ~1,000 games (expandable). How their positive-review percentage moves month by month, with patches and announcements marked on the chart.

Constraints: the scraper must be **pausable and resumable** (no multi-day runs), and the site must be **fully static** so it works on GitHub Pages now and on a personal domain later. The project should be presentable enough for a CV.

---

## 1. Data sources (tested 2026-11-18)

| Purpose | Endpoint | Auth | Notes |
|---|---|---|---|
| All app IDs | `api.steampowered.com/IStoreService/GetAppList/v1/` | **Steam Web API key** (403 without) | Paginated (`last_appid`, `max_results` ≤ 50k), with filters like `include_games=1` and `include_dlc=0`. A free key comes from steamcommunity.com/dev/apikey. |
| Tags with weights, review summary, release date, price | `api.steampowered.com/IStoreBrowseService/GetItems/v1/?input_json=…` | none | **Batched**: many app IDs per request. Returns `tags: [{tagid, weight}]` (top 20), `reviews.summary_filtered.{review_count, percent_positive}`, `release.original_steam_release_date` and `best_purchase_option`. This is the main source for the tag dataset. |
| Tag ID → name | `api.steampowered.com/IStoreService/GetTagList/v1/?language=english` | none | One call. |
| Monthly review history | `store.steampowered.com/appreviewhistogram/{appid}?l=english&review_score_preference=0` | none | `results.rollups[]` = `{date, recommendations_up, recommendations_down}` per month for the game's whole life. One call per game. |
| Patch notes and events | `api.steampowered.com/ISteamNews/GetNewsForApp/v2/?appid=…&count=…` | none | Used for the timeline markers. |
| Exact review counts (optional) | `store.steampowered.com/appreviews/{appid}?json=1&num_per_page=0&purchase_type=all` | none | `query_summary.total_positive/total_negative`. Only needed if the integer-rounded `percent_positive` from GetItems turns out to be too coarse. |
| Fallback app list | `steamspy.com/api.php?request=all&page=N` | none | 1,000 apps per page, max 1 request per 60 s. Use only if no API key is available. |

**Effect on scrape time:** because GetItems is batched, the full tag dataset should take **under ~1–2 hours of total runtime**, not days. Pausability is still built in from the start, because histograms, news and future refreshes are per-game calls.

### Scrape budget estimate
| Stage | Calls | Est. time at a polite rate |
|---|---|---|
| App list | ~3–5 pages | < 1 min |
| GetItems (~150k games ÷ 200 per batch, measured) | ~750 | 15–20 min |
| Histograms (top 1k) | 1k | ~20 min |
| News (top 1k) | 1k | ~20 min |

The real batch size and safe request rate get measured in Milestone 1. Expanding the timelines to 5–10k games is cheap if that's wanted later.

---

## 2. Architecture

```
            ┌───────────────────── pipeline/ (Python) ─────────────────────┐
 Steam APIs │  fetch  ──►  raw cache (SQLite)  ──►  build  ──►  analysis   │
            │   ▲  job queue + resumable state       DuckDB      stats     │
            └───┴──────────────────────────────────────────┬───────────────┘
                                                           │ export
                                                           ▼
                                     web/public/data/*.parquet | *.json
                                                           │
            ┌────────────── web/ (Vite + React + TS, static) ┴─────────────┐
            │  DuckDB-WASM queries over Parquet · charts · routing         │
            └──────────────────────────────────────────────────────────────┘
                     │ GitHub Actions build → GitHub Pages (later: own domain)
```

The website never calls Steam. It reads only precomputed files, so hosting is just a folder of files.

---

## 3. Repository layout

```
steam-tag-analysis/
├── README.md                # demo link, GIF, summary, how to run
├── PLAN.md
├── pyproject.toml           # uv-managed; ruff, pytest config
├── .env.example             # STEAM_API_KEY=
├── pipeline/
│   ├── cli.py               # Typer CLI entry: `stp fetch|build|analyze|export`
│   ├── config.py
│   ├── db.py                # SQLite connection, schema, migrations
│   ├── fetch/
│   │   ├── client.py        # httpx client, rate limiter, retries, backoff
│   │   ├── jobs.py          # job queue: enqueue / claim / complete / fail
│   │   ├── applist.py
│   │   ├── items.py         # GetItems batches
│   │   ├── histograms.py
│   │   └── news.py
│   ├── build/               # raw JSON → clean tables (DuckDB)
│   ├── analysis/
│   │   ├── shrinkage.py     # empirical-Bayes beta-binomial
│   │   ├── combos.py        # pair/triple mining, lift, interaction effects
│   │   ├── model.py         # baseline additive model (ridge on tag dummies)
│   │   └── timelines.py     # monthly %, drift, change points, news alignment
│   └── export/              # writes web/public/data/
├── notebooks/               # exploration only, not part of the pipeline
├── tests/                   # analysis math + parsers (fixtures from real responses)
├── data/                    # gitignored: steam.sqlite, analysis.duckdb
└── web/
    ├── vite.config.ts       # `base` from env → portable hosting
    ├── src/
    │   ├── pages/           # Home, TagExplorer, HiddenGems, Timelines, Findings, Methodology
    │   ├── components/
    │   ├── data/            # DuckDB-WASM init + typed query helpers
    │   └── lib/
    └── public/data/         # exported artifacts (committed or built in CI)
```

---

## 4. Pipeline design

### 4.1 Pausable, resumable fetching (core requirement)
All fetch state lives in SQLite (`data/steam.sqlite`), so stopping the process at any moment loses at most the request in flight.

**Tables**
- `jobs(kind, key, status, attempts, last_error, updated_at)`. `kind` ∈ `applist_page | items_batch | histogram | news`, and `status` ∈ `pending | done | failed`. Primary key `(kind, key)`.
- `raw_responses(kind, key, fetched_at, status_code, body_gz)`. The gzipped raw JSON is never thrown away, so parsers can be re-run without re-fetching.
- `meta(key, value)` for the app-list cursor, tag-list version hash and so on.

**Behavior**
- `stp fetch items` enqueues the missing jobs, then processes pending ones. Each job's result and its `done` status are written in **one transaction**, so it's crash-safe.
- **Ctrl+C** triggers a graceful stop: finish the current request, commit, exit. A hard kill or power loss is also safe because of the transactions.
- `--budget 30m` / `--max-requests N` stops cleanly after a time or request limit, for short sessions.
- Re-running the same command resumes where it stopped. `stp status` shows progress per stage (done/pending/failed and an ETA).
- Rate limiting uses a token bucket (configurable requests per second) with jitter. On 429 or 5xx: exponential backoff, honoring `Retry-After`. After N failures a job is marked `failed` and can be retried later with `stp fetch --retry-failed`.
- Refreshes: jobs carry `fetched_at`. `stp fetch histograms --stale-after 30d` re-queues only outdated entries, for monthly updates.

### 4.2 Fetch stages
1. **App list**: GetAppList (games only) → `apps(appid, name, last_modified)`.
2. **Items**: GetItems in batches → tags with weights, review summary, release date, price, type.
3. **Tag list**: one call → `tags(tagid, name)`.
4. **Select the timeline set**: the top N games by `review_count` (N=1000 by default, configurable). Optionally add a stratified sample of mid-size games so the set isn't popularity-only.
5. **Histograms** for the timeline set.
6. **News** for the timeline set. Only items with feed type "patch notes / announcements" are kept.

### 4.3 Build (raw → clean, DuckDB)
- `games(appid, name, release_date, price_usd, is_free, is_early_access, review_count, pct_positive, n_pos, n_neg)`
- `game_tags(appid, tagid, rank, weight, weight_share)`, where `weight_share = weight / max weight for that game`
- `tags(tagid, name, n_games)`
- `review_monthly(appid, month, up, down)`
- `news(appid, date, title, url, feed)`
- Filters: game type only, `review_count ≥ 20`, no adult-only/test apps.

**Tag relevance rule** (important for "obscure" combos): a tag counts for a game only if it is in the game's **top 10 tags by votes** (about 9.3 tags per game). A vote-share cutoff was tested and dropped: shares decline so slowly that even the 20th tag has a median of 35% of the top tag's votes, so the cutoff readmitted almost everything (see `notebooks/01_explore_tags.ipynb`). The rank cutoff is a config value, and the site's methodology page shows a sensitivity check.

---

## 5. Analysis

### 5.1 Game-level score
Raw `n_pos / n` is noisy for small games. Fit a **beta-binomial prior** to all games (empirical Bayes) and use each game's posterior mean as its score. A game with 20 reviews moves toward the global mean; one with 200k reviews keeps its own score. Every game counts once, so big titles don't dominate a combo.

### 5.2 Combo statistics
- **Mining**: count co-occurrence for all tag pairs and triples among relevant tags, with minimum support (≥ 15 games, configurable). Apriori-style pruning keeps triples manageable.
- **For each combo**: `n_games`, mean shrunken score, bootstrap 90% CI, median review count, median release year.
- **Expected score**: fit a **ridge-regularized additive model**: logit(score) ~ Σ tag dummies, plus release-year and price controls. The combo's **interaction effect** = mean residual of games that have the combo. This is the main "this mix outperforms its parts" number.
- **Simpler lift metric** for display: combo mean − mean of its single-tag means.
- **Multiple-comparison caution**: thousands of combos means some look great by chance. Rank by the CI lower bound, apply a Benjamini-Hochberg flag, and say this on the methodology page.

### 5.3 "Hidden gems" ranking
Combos with **low support (15–100 games)**, a **high interaction effect** and a **tight CI**, excluding combos made of near-synonym tags (e.g. "Roguelike" + "Roguelite") detected by very high co-occurrence.

### 5.4 Timelines
For each game in the timeline set:
- monthly % positive, cumulative %, and 3-month rolling %, with months under ~20 reviews faded out
- **launch score** (first 3 months) vs **current score**, and **drift**
- **change-point detection** (`ruptures`, PELT) on the monthly series, with each change point matched to the nearest news item within ±30 days ("dip after update 1.4", "recovery after patch")
- aggregate views: average trajectory by primary tag, normalized to months since release

### 5.5 Known biases (shown on the Methodology page)
Survivorship (delisted games are missing). Early-access start dates are missing for many older games (e.g. Rust shows its 2018 1.0 date, not 2013), so release-year controls are approximate; for the timeline set, the first month with reviews is used instead. Tags are today's tags, not the ones at launch. `summary_filtered` excludes off-topic review bombs. GetItems' `percent_positive` is rounded to an integer. Free-to-play and early-access games are flagged and filterable. The timeline set is biased toward popular games.

---

## 6. Export (pipeline → web)

| File | Contents | Expected size |
|---|---|---|
| `games.parquet` | game rows with shrunken score and core fields | ~2–4 MB |
| `game_tags.parquet` | relevant tags per game | ~2–3 MB |
| `tags.json` | tag ID → name, game count | small |
| `combos_pairs.parquet` / `combos_triples.parquet` | precomputed stats + effects | ~1–5 MB |
| `timelines/index.json` | timeline set: appid, name, summary metrics | small |
| `timelines/{appid}.json` | monthly series + change points + news markers, **lazy-loaded** | ~5–20 KB each |
| `meta.json` | scrape date, thresholds used, counts | tiny |

The Parquet files are loaded into **DuckDB-WASM**, so the explorer can run arbitrary user-chosen combos (e.g. 4 tags, custom filters) in the browser, not just the precomputed ones.

---

## 7. Website

**Stack:** Vite + React + TypeScript, React Router, DuckDB-WASM, Observable Plot (charts), plus d3-force for the co-occurrence network. Tailwind or CSS modules for styling. Light and dark theme.

### Pages
1. **Home**: one-sentence pitch, three headline findings as cards, links into both tools.
2. **Tag Explorer**
   - tag picker (autocomplete, multi-select) → live stats for that exact combo, with its CI and the games in it
   - "best companions" table for the chosen tags: which added tag raises or lowers the score most
   - scatter plot: combo popularity (n games) vs interaction effect, hover for details
   - filters: release year range, price, free-to-play, early access, minimum reviews
   - tag co-occurrence network (top ~150 tags), colored by average score
3. **Hidden Gems**: a curated, sortable list from §5.3, each item linking into the explorer.
4. **Timelines**
   - game search → monthly % chart with news markers and change-point annotations
   - compare up to 4 games, aligned by calendar date or by months since release
   - leaderboards: biggest recoveries, biggest declines, most stable
   - tag-aggregate trajectories
5. **Findings**: 5–10 written insights with embedded charts. This is the page someone reads in 30 seconds.
6. **Methodology**: data sources, the shrinkage and interaction model in plain language, thresholds, biases, scrape date.

### Portable hosting
- `base` in `vite.config.ts` comes from `VITE_BASE` (`/steam-tag-analysis/` for GitHub Pages, `/` or `/steam/` for your own domain).
- All data fetches use `import.meta.env.BASE_URL`, so there are no hard-coded absolute paths.
- **Hash router** (or a `404.html` SPA redirect) so deep links work on GitHub Pages without server config.
- Moving to your own domain = change `VITE_BASE` and deploy the same `dist/` folder anywhere.

### Quality bar
Responsive down to phone width. Loading states while DuckDB-WASM initializes (about 1–2 s). Shareable URLs (state in query params, e.g. `#/explore?tags=Roguelike,Farming`). Basic accessibility (keyboard navigation, chart alt text, color-blind-safe palette). Lighthouse performance check.

---

## 8. Engineering and CI

- **Python**: 3.12, `uv`, `httpx`, `duckdb`, `polars`, `numpy`/`scipy`, `scikit-learn` (ridge), `ruptures`, `typer`, `rich` (progress bars). `ruff` + `pytest`.
- **Tests**: parsers against saved real responses (fixtures); shrinkage and lift math against hand-computed cases; job-queue resume behavior (kill mid-run, verify no duplicate or lost jobs).
- **Web**: ESLint, TypeScript strict, Vitest for the query helpers.
- **GitHub Actions**
  - `ci.yml`: lint and test both halves on every push and PR.
  - `deploy.yml`: build `web/` and deploy to Pages on push to `main`.
  - The data refresh stays **local** for now (`stp fetch … && stp build && stp analyze && stp export`, then commit the exported files). A scheduled incremental refresh in Actions is possible later, since incremental updates fit well inside the 6-hour job limit.
- **Secrets**: `STEAM_API_KEY` goes in `.env` (gitignored). Raw data and `data/` are never committed; only the aggregated exports are published.

---

## 9. Milestones

### M0 — Setup (½ day)
- [ ] git init, repo skeleton, `uv` project, ruff/pytest, `.env.example`, `.gitignore`
- [ ] Vite + React + TS app skeleton with `VITE_BASE` wiring and a deploy workflow (an empty site live on Pages early)

### M1 — Resumable fetcher (1–2 days)
- [ ] SQLite schema, job queue, rate-limited client with backoff
- [ ] Graceful Ctrl+C, `--budget`, `stp status`
- [ ] Stages: applist → items → taglist
- [x] Measure the real GetItems batch limit (200 OK, 400 rejected) and record it in config
- [ ] Confirm a safe sustained request rate during the first full run
- [ ] Test: interrupt and resume with no lost or duplicated jobs

### M2 — Build + first exploration (1–2 days)
- [x] Raw → clean tables in DuckDB (`stp build`, ~26 s)
- [x] Notebook: tag distributions, choosing the tag relevance thresholds, sanity checks against the Steam store (`notebooks/01_explore_tags.ipynb`)
- [x] Tag relevance rule decided: top 10 tags by votes only

### M3 — Tag-mix analysis (2–3 days)
- [ ] Shrinkage, combo mining, additive model, interaction effects, CIs
- [ ] Notebook: first candidate "hidden gems". Check that they're real and not tag synonyms or noise
- [ ] Export to Parquet and JSON

### M4 — Tag Explorer + Hidden Gems pages (3–4 days)
- [ ] DuckDB-WASM data layer, tag picker, combo stats, companions table, scatter plot, filters, URL state
- [ ] Co-occurrence network

### M5 — Timelines pipeline (1–2 days)
- [ ] Timeline-set selection, histogram + news fetch stages (resumable, same queue)
- [ ] Monthly metrics, change points, news alignment, export

### M6 — Timelines page (2–3 days)
- [ ] Single-game chart with markers, comparison mode, leaderboards, tag-aggregate trajectories

### M7 — Story and polish (2–3 days)
- [ ] Findings and Methodology pages, Home page
- [ ] Responsive and dark-mode pass, accessibility, performance
- [ ] README with a GIF, architecture diagram and live link

Total: roughly 3–4 weeks of part-time work. Each milestone produces something usable on its own.

---

## 10. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Undocumented endpoints (GetItems, histogram) change or get stricter | Raw responses are cached, so the analysis survives; parsers are isolated per endpoint; SteamSpy is a fallback for tags and summaries |
| Rate limiting / IP throttling | Conservative token bucket, backoff, budgeted sessions; the total call count is low thanks to batching |
| No API key available | SteamSpy `request=all` as the app list (slower, slightly incomplete coverage) |
| "Interesting" combos are statistical noise | Shrinkage, CI-lower-bound ranking, minimum support, multiple-comparison flag, manual review in M3 |
| Tag synonyms dominate the results | Detect near-synonym pairs (co-occurrence ratio), exclude or merge them |
| DuckDB-WASM bundle size / load time | Lazy-load it only on the Explorer page; the precomputed JSON views render first |

---

## 11. Open decisions
- Get a Steam Web API key (recommended) or use the SteamSpy fallback.
- Timeline set size: 1k to start. Expanding to 5k is cheap if the first results are interesting.
- Project name and repo name (used in the Pages URL, e.g. `you.github.io/<repo>/`).
- Whether exported data files are committed or built in CI (default: committed, since they're small and reproducible).
