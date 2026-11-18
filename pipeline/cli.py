"""`stp` command-line interface.

Every fetch command is resumable: stop it any time (Ctrl+C, --budget, closing the
terminal) and run the same command again to continue.
"""

from __future__ import annotations

import time
from typing import Annotated

import typer
from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn, TimeRemainingColumn
from rich.table import Table

from pipeline import db
from pipeline.config import DB_PATH, FETCH, steam_api_key
from pipeline.fetch import applist, items, jobs, taglist
from pipeline.fetch.client import FetchError, SteamClient
from pipeline.fetch.control import RunControl, parse_duration

app = typer.Typer(help="Steam tag-mix & review-timeline pipeline.", no_args_is_help=True)
fetch_app = typer.Typer(help="Resumable data fetching.", no_args_is_help=True)
probe_app = typer.Typer(help="Measure endpoint limits.", no_args_is_help=True)
app.add_typer(fetch_app, name="fetch")
app.add_typer(probe_app, name="probe")
console = Console()

Budget = Annotated[
    str | None, typer.Option("--budget", "-b", help="Stop after this long, e.g. 30m, 1h30m.")
]
MaxRequests = Annotated[
    int | None, typer.Option("--max-requests", help="Stop after this many HTTP requests.")
]


def _control(budget: str | None, max_requests: int | None) -> RunControl:
    try:
        budget_s = parse_duration(budget) if budget else None
    except ValueError as e:
        raise typer.BadParameter(str(e)) from e
    return RunControl(budget_s=budget_s, max_requests=max_requests)


def _require_key() -> str:
    key = steam_api_key()
    if not key:
        console.print(
            "[red]STEAM_API_KEY is not set.[/red] Copy .env.example to .env and add your key "
            "(https://steamcommunity.com/dev/apikey)."
        )
        raise typer.Exit(1)
    return key


def _report_stop(reason: str | None, what: str) -> None:
    if reason:
        console.print(f"[yellow]Paused {what}: {reason}.[/yellow] Run the same command to resume.")
    else:
        console.print(f"[green]{what.capitalize()} complete.[/green]")


# --- fetch stages -------------------------------------------------------------


def _run_applist(conn, client, refresh: bool) -> str | None:
    if refresh:
        applist.reset(conn)
    if applist.is_complete(conn):
        n = conn.execute("SELECT COUNT(*) FROM apps").fetchone()[0]
        console.print(f"App list already complete ({n:,} games). Use --refresh to re-list.")
    else:
        key = _require_key()
        reason = applist.run(
            conn,
            client,
            key,
            on_page=lambda got, total: console.print(f"  page: +{got:,} apps (total {total:,})"),
        )
        _report_stop(reason, "app list")
        if reason:
            return reason
    new = applist.enqueue_all(conn, items.KIND)
    if new:
        console.print(f"Queued {new:,} new apps for item details.")
    return None


def _run_getitems(conn, client, batch_size: int, kind: str = items.KIND) -> str | None:
    label = {items.KIND: "item details", items.BASIC_KIND: "developer info"}[kind]
    pending = jobs.pending_count(conn, kind)
    if pending == 0:
        console.print(f"No pending {kind} jobs.")
        return None
    with Progress(
        TextColumn(f"[bold]{kind}[/bold]"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        task = progress.add_task(kind, total=pending)
        reason = items.run(
            conn, client, batch_size, on_batch=lambda n: progress.advance(task, n), kind=kind
        )
    _report_stop(reason, label)
    failed = jobs.counts(conn).get(kind, {}).get(jobs.FAILED, 0)
    if failed:
        console.print(
            f"[yellow]{failed:,} {kind} jobs failed[/yellow] — `stp fetch {kind} --retry-failed`."
        )
    return reason


def _queue_basic(conn) -> None:
    from pipeline.config import BUILD

    new = items.enqueue_basic(conn, BUILD.min_reviews)
    if new:
        console.print(f"Queued {new:,} games ({BUILD.min_reviews}+ reviews) for developer info.")


@fetch_app.command("applist")
def fetch_applist(
    refresh: Annotated[bool, typer.Option(help="Re-list all apps from scratch.")] = False,
    budget: Budget = None,
    max_requests: MaxRequests = None,
):
    """List all Steam games (needs STEAM_API_KEY) and queue them for item details."""
    conn = db.connect()
    control = _control(budget, max_requests)
    with control.handle_sigint(), SteamClient(control) as client:
        _run_applist(conn, client, refresh)


@fetch_app.command("items")
def fetch_items(
    batch_size: Annotated[int, typer.Option(help="Apps per request.")] = FETCH.items_batch_size,
    retry_failed: Annotated[bool, typer.Option(help="Re-queue failed jobs first.")] = False,
    stale_after: Annotated[
        str | None, typer.Option(help="Re-fetch apps older than this, e.g. 30d.")
    ] = None,
    budget: Budget = None,
    max_requests: MaxRequests = None,
):
    """Fetch tags, review summary, release date and price for queued apps."""
    conn = db.connect()
    if retry_failed:
        console.print(f"Re-queued {jobs.retry_failed(conn, items.KIND):,} failed jobs.")
    if stale_after:
        n = jobs.requeue_stale(conn, items.KIND, parse_duration(stale_after))
        console.print(f"Re-queued {n:,} stale jobs.")
    control = _control(budget, max_requests)
    with control.handle_sigint(), SteamClient(control) as client:
        _run_getitems(conn, client, batch_size)


@fetch_app.command("basic")
def fetch_basic(
    batch_size: Annotated[int, typer.Option(help="Apps per request.")] = FETCH.items_batch_size,
    retry_failed: Annotated[bool, typer.Option(help="Re-queue failed jobs first.")] = False,
    budget: Budget = None,
    max_requests: MaxRequests = None,
):
    """Fetch developers, publishers and franchises for games with enough reviews."""
    conn = db.connect()
    _queue_basic(conn)
    if retry_failed:
        console.print(f"Re-queued {jobs.retry_failed(conn, items.BASIC_KIND):,} failed jobs.")
    control = _control(budget, max_requests)
    with control.handle_sigint(), SteamClient(control) as client:
        _run_getitems(conn, client, batch_size, items.BASIC_KIND)


@fetch_app.command("taglist")
def fetch_taglist(refresh: Annotated[bool, typer.Option()] = False):
    """Fetch the tag ID → name list."""
    conn = db.connect()
    with SteamClient(RunControl()) as client:
        n = taglist.run(conn, client, refresh)
    console.print(f"[green]{n:,} tags cached.[/green]")


@fetch_app.command("all")
def fetch_all(
    batch_size: Annotated[
        int, typer.Option(help="Apps per items request.")
    ] = FETCH.items_batch_size,
    budget: Budget = None,
    max_requests: MaxRequests = None,
):
    """Run every stage in order: applist → taglist → items → basic. Resumable."""
    conn = db.connect()
    control = _control(budget, max_requests)
    with control.handle_sigint(), SteamClient(control) as client:
        if _run_applist(conn, client, refresh=False):
            return
        n = taglist.run(conn, client)
        console.print(f"{n:,} tags cached.")
        if _run_getitems(conn, client, batch_size):
            return
        _queue_basic(conn)
        _run_getitems(conn, client, batch_size, items.BASIC_KIND)


# --- build --------------------------------------------------------------------


@app.command()
def build():
    """Rebuild clean analysis tables (data/analysis.duckdb) from the raw cache."""
    from pipeline.build import tables
    from pipeline.config import ANALYSIS_DB_PATH, BUILD

    t0 = time.monotonic()
    counts = tables.run(db.connect())
    console.print(f"[green]Built {ANALYSIS_DB_PATH}[/green] in {time.monotonic() - t0:.0f}s")
    console.print(
        f"  games: {counts['games']:,} ({counts['games_min_reviews']:,} with "
        f"{BUILD.min_reviews}+ reviews) | game_tags: {counts['game_tags']:,} | "
        f"tags: {counts['tags']:,}"
    )


@app.command()
def analyze():
    """Score games, fit the baseline model and compute combo statistics."""
    from pipeline.analysis import run as analysis

    t0 = time.monotonic()
    analysis.run(log=lambda msg: console.print(f"  {msg}"))
    console.print(f"[green]Analysis done[/green] in {time.monotonic() - t0:.0f}s")


@app.command()
def export():
    """Write the website's data files to web/public/data/."""
    from pipeline.export import web

    sizes = web.run()
    for name, size in sizes.items():
        console.print(f"  {name:<20} {size / 1e6:6.2f} MB")
    console.print(f"[green]Exported to {web.WEB_DATA_DIR}[/green]")


# --- status & probes ----------------------------------------------------------


@app.command()
def status():
    """Show progress of every fetch stage."""
    conn = db.connect()
    n_apps = conn.execute("SELECT COUNT(*) FROM apps").fetchone()[0]
    console.print(f"Database: {DB_PATH}")
    state = "complete" if applist.is_complete(conn) else "in progress" if n_apps else "not started"
    console.print(f"App list: {n_apps:,} games ({state})")
    console.print(
        f"Tag list: {'cached' if db.get_raw(conn, taglist.KIND, 'english') else 'not fetched'}"
    )

    table = Table("stage", "done", "pending", "failed", "progress")
    for kind, c in sorted(jobs.counts(conn).items()):
        total = sum(c.values())
        pct = f"{100 * c[jobs.DONE] / total:.1f}%" if total else "-"
        table.add_row(kind, f"{c[jobs.DONE]:,}", f"{c[jobs.PENDING]:,}", f"{c[jobs.FAILED]:,}", pct)
    console.print(table)


@probe_app.command("items-batch")
def probe_items_batch(
    sizes: Annotated[
        str, typer.Option(help="Comma-separated batch sizes to try.")
    ] = "50,100,200,400,800",
):
    """Try increasing GetItems batch sizes on known games and report what Steam returns."""
    conn = db.connect()
    appids = [r[0] for r in conn.execute("SELECT appid FROM apps ORDER BY appid LIMIT 1000")]
    if len(appids) < 50:
        console.print("[red]Need the app list first:[/red] stp fetch applist")
        raise typer.Exit(1)
    table = Table("batch size", "returned", "seconds", "result")
    with SteamClient(RunControl()) as client:
        for size in (int(s) for s in sizes.split(",")):
            batch = appids[:size]
            t0 = time.monotonic()
            try:
                _, by_id = items.fetch_batch(client, batch)
                table.add_row(
                    str(size), f"{len(by_id)}/{len(batch)}", f"{time.monotonic() - t0:.1f}", "ok"
                )
            except FetchError as e:
                table.add_row(str(size), "-", f"{time.monotonic() - t0:.1f}", f"[red]{e}[/red]")
                break
    console.print(table)


if __name__ == "__main__":
    app()
