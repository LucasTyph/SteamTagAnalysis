# Steam Tag Analysis

Which combinations of Steam user tags do better than their parts, and how do games' review
scores move over time?

- **Tag Mix Explorer**: every Steam game with 20+ reviews, with tag-combination effects
  adjusted for small samples.
- **Review Timelines**: month-by-month positive-review % for the top ~1,000 games, with patch
  notes marked on the chart.

> Live demo: _coming soon_

See [PLAN.md](PLAN.md) for the full design.

## Layout

```
pipeline/   Python: resumable fetch → build → analysis → export
web/        Static site (Vite + React + TS), deployable anywhere
tests/      pytest suite
data/       local SQLite cache (gitignored)
```

## Pipeline quick start

```bash
python -m venv .venv
.venv/Scripts/activate        # Windows; use `source .venv/bin/activate` elsewhere
pip install -e ".[analysis,notebook,dev]"
cp .env.example .env          # then add STEAM_API_KEY
```

```bash
stp fetch all --budget 30m    # applist → taglist → items → basic; resumable
stp status                    # progress per stage
stp build && stp analyze && stp export   # tables → statistics → web/public/data
```

Every fetch command can be stopped at any time (Ctrl+C, `--budget`, `--max-requests`, or just
closing the terminal) and resumed by running the same command again. State and raw responses
are kept in `data/steam.sqlite`. Each result is committed in the same transaction that marks
its job done, so an interrupted run never loses or duplicates work.

Other useful commands:

```bash
stp fetch items --retry-failed     # re-queue jobs that failed 3 times
stp fetch items --stale-after 30d  # refresh old data
stp probe items-batch              # measure the largest GetItems batch Steam accepts
```

## Website

```bash
cd web
npm install
npm run dev
```

`VITE_BASE` sets the path the site is served from (`/<repo>/` on GitHub Pages, `/` on your own
domain). The deploy workflow sets it automatically for Pages.

## Tests

```bash
ruff check . && pytest
```
