"""`stp track …` commands."""

from __future__ import annotations

import gzip
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from pipeline.config import ROOT, steam_api_key
from pipeline.fetch.client import SteamClient
from pipeline.fetch.control import RunControl, parse_duration
from pipeline.tracking.daily import TRACKING, run_daily, seed_from_raw
from pipeline.tracking.store import COMING_SOON, TrackingStore

track_app = typer.Typer(help="Daily tracking of new releases (first year).", no_args_is_help=True)
console = Console()

DEFAULT_DIR = ROOT / "tracking-data"
Dir = Annotated[Path, typer.Option("--dir", help="Tracking data directory.")]


def _today(value: str | None) -> date:
    return date.fromisoformat(value) if value else datetime.now(UTC).date()


@track_app.command("seed")
def seed(
    dir: Dir = DEFAULT_DIR,
    today: Annotated[str | None, typer.Option(help="Override today (YYYY-MM-DD).")] = None,
):
    """Start the catalog from the local GetItems cache (no requests)."""
    from pipeline import db

    store = TrackingStore(dir)
    if (dir / "catalog.csv").exists():
        console.print(f"[red]{dir / 'catalog.csv'} already exists; refusing to overwrite.[/red]")
        raise typer.Exit(1)
    conn = db.connect()
    rows = conn.execute("SELECT key, body_gz, fetched_at FROM raw_responses WHERE kind = 'items'")
    raw = ((k, json.loads(gzip.decompress(b)), f) for k, b, f in rows)
    stats = seed_from_raw(store, raw, _today(today))
    console.print(
        f"[green]Seeded {dir}[/green]: {stats['coming_soon']:,} coming-soon games watched, "
        f"{stats['tracked']:,} recent releases tracked."
    )


@track_app.command("daily")
def daily(
    dir: Dir = DEFAULT_DIR,
    budget: Annotated[
        str | None, typer.Option("--budget", "-b", help="Stop after this long, e.g. 5h.")
    ] = None,
    max_requests: Annotated[int | None, typer.Option("--max-requests")] = None,
    today: Annotated[str | None, typer.Option(help="Override today (YYYY-MM-DD).")] = None,
    skip_if_done: Annotated[
        bool,
        typer.Option(
            "--skip-if-done",
            help="Exit without doing anything if today's run already completed "
            "(for a backup schedule).",
        ),
    ] = False,
):
    """Run one day of tracking. Safe to re-run; a cut-short run resumes next time."""
    store = TrackingStore(dir)
    if not (dir / "catalog.csv").exists():
        console.print("[red]No catalog yet.[/red] Run `stp track seed` first.")
        raise typer.Exit(1)
    day = _today(today)
    if skip_if_done and store.load_state().get("last_run") == day.isoformat():
        console.print(f"Today's run ({day}) already completed; nothing to do.")
        return
    control = RunControl(
        budget_s=parse_duration(budget) if budget else None, max_requests=max_requests
    )
    with control.handle_sigint(), SteamClient(control) as client:
        stats = run_daily(
            store,
            client,
            day,
            steam_api_key(),
            TRACKING,
            log=lambda m: console.print(f"  {m}"),
        )
    console.print(
        f"[green]Done[/green] in {stats['duration_s']}s, {stats['requests']:,} requests"
        + (f" (stopped: {stats['stop_reason']})" if stats["stop_reason"] else "")
    )


def _read_runs(dir: Path) -> list[dict]:
    import csv

    path = dir / "runs.csv"
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


@track_app.command("status")
def status(dir: Dir = DEFAULT_DIR):
    """Summarize the tracking data."""
    store = TrackingStore(dir)
    catalog = store.load_catalog()
    state = store.load_state()
    today = datetime.now(UTC).date()
    table = Table("", "value")
    runs = _read_runs(dir)
    if runs:
        last = runs[-1]
        how = f"stopped early: {last['stop_reason']}" if last["stop_reason"] else "complete"
        table.add_row("last run", f"{last['date']} ({how}, {last['requests']} requests)")
        table.add_row("daily counts still due", last["histograms_pending"] or "0")
    else:
        table.add_row("last run", "never")
    table.add_row("last complete run", state.get("last_run", "never"))
    table.add_row(
        "coming soon (watched)", f"{sum(e.status == COMING_SOON for e in catalog.values()):,}"
    )
    table.add_row("tracked now", f"{sum(e.is_tracked(today) for e in catalog.values()):,}")
    table.add_row(
        "snapshot files", str(len(list((dir / "snapshots").glob("*.csv")))) if dir.exists() else "0"
    )
    table.add_row(
        "daily-count files",
        str(len(list((dir / "daily_reviews").glob("*.csv")))) if dir.exists() else "0",
    )
    console.print(table)


@track_app.command("check")
def check(
    dir: Dir = DEFAULT_DIR,
    today: Annotated[str | None, typer.Option(help="Override today (YYYY-MM-DD).")] = None,
):
    """Exit with an error unless today's run has completed (used for alerts)."""
    day = _today(today)
    last = TrackingStore(dir).load_state().get("last_run")
    if last == day.isoformat():
        console.print(f"OK: the run for {day} completed.")
        return
    runs = _read_runs(dir)
    detail = ""
    if runs and runs[-1]["date"] == day.isoformat() and runs[-1]["stop_reason"]:
        detail = f" Today's run stopped early: {runs[-1]['stop_reason']}."
    console.print(f"[red]Not complete:[/red] last completed run is {last or 'never'}.{detail}")
    raise typer.Exit(1)
