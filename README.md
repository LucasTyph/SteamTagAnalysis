# Release tracking data

Written once a day by the `Track new releases` workflow on `main`
(`stp track daily`, code in `pipeline/tracking/`). Every Steam game is tracked from
its release for 365 days.

| File | Contents |
|---|---|
| `catalog.csv` | Games being watched (`coming_soon`, re-checked daily near their planned date, weekly otherwise) or tracked (`released`, with `release_date` and `tracked_from`). Retired after their year. |
| `snapshots/YYYY-MM.csv` | One row per tracked game per day: `review_count` and `pct_positive` (whole percent, as Steam reports it). |
| `daily_reviews/YYYY-MM.csv` | Exact positive (`up`) and negative (`down`) reviews per game per day, from Steam's 30-day review histogram, refreshed at least every 21 days so no day is missed. Later fetches overwrite earlier ones. |
| `runs.csv` | One row per run: requests, discoveries, newly tracked games, errors, and whether it stopped early. |
| `state.json` | App-list cursor (`applist_since`) and last run date. |

Files are plain sorted CSV so each daily commit stores only what changed.
