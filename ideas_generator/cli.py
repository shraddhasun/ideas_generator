from __future__ import annotations

import io
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from ideas_generator import db as dbm
from ideas_generator.cluster import rebuild_clusters
from ideas_generator.config import discover_dotenv_paths, get_settings, parse_bare_api_keys_from_dotenv_files
from ideas_generator.connectors.hn import fetch_hn_items
from ideas_generator.connectors.reddit import fetch_reddit_items
from ideas_generator.connectors.stackexchange import fetch_stackexchange_items
from ideas_generator.embed import run_embed
from ideas_generator.llm_screen import run_llm_screen
from ideas_generator.llm_util import llm_screen_enabled
from ideas_generator.filters import is_healthcare_related
from ideas_generator.models import RawItem
from ideas_generator.score import compute_cluster_scores, persist_snapshots
from ideas_generator.report import report_csv, report_markdown

app = typer.Typer(no_args_is_help=True, help="Business problem finder pipeline.")
console = Console()


def _connect():
    s = get_settings()
    conn = dbm.connect(s.database_path)
    return conn, s


def _ingest_impl(source: str) -> tuple[int, int]:
    conn, settings = _connect()
    dbm.init_db(conn)
    raw: list[RawItem] = []

    fetch_hn = source in ("hn", "hn-stackexchange", "all")
    fetch_se = source in ("stackexchange", "hn-stackexchange", "all")
    fetch_reddit = source in ("reddit", "all")

    if fetch_hn:
        console.print("Fetching Hacker News…")
        raw.extend(fetch_hn_items(settings.hn_lookback_seconds))

    if fetch_se:
        sites = [x.strip() for x in settings.stackexchange_sites.split(",") if x.strip()]
        console.print(f"Fetching Stack Exchange ({', '.join(sites)})…")
        raw.extend(fetch_stackexchange_items(sites))

    if fetch_reddit:
        if settings.reddit_client_id and settings.reddit_client_secret:
            subs = [x.strip() for x in settings.reddit_subreddits.split(",") if x.strip()]
            console.print(f"Fetching Reddit ({', '.join(subs)})…")
            raw.extend(
                fetch_reddit_items(
                    settings.reddit_client_id,
                    settings.reddit_client_secret,
                    settings.reddit_user_agent,
                    subs,
                )
            )
        elif source == "reddit":
            console.print(
                "[red]Reddit requires IDEAS_REDDIT_CLIENT_ID and IDEAS_REDDIT_CLIENT_SECRET in .env[/red]"
            )
            raise typer.Exit(code=1)
        else:
            console.print("[dim]Skipping Reddit (add credentials later; use --source all to include when ready).[/dim]")

    n = 0
    nh = 0
    with dbm.transaction(conn):
        for item in raw:
            drop = None
            if is_healthcare_related(item.text, item.url):
                drop = "healthcare"
                nh += 1
            dbm.upsert_item(conn, item, dropped_reason=drop)
            n += 1

    conn.close()
    return n, nh


@app.command()
def init_db() -> None:
    """Create SQLite schema."""
    conn, _ = _connect()
    dbm.init_db(conn)
    conn.close()
    console.print("[green]Database initialized.[/green]")


@app.command()
def ingest(
    source: str = typer.Option(
        "hn-stackexchange",
        "--source",
        "-s",
        help="hn-stackexchange (default) | hn | stackexchange | reddit | all",
    ),
) -> None:
    """Fetch from configured APIs and upsert into SQLite."""
    n, nh = _ingest_impl(source)
    console.print(f"[green]Upserted {n} items[/green] ({nh} flagged healthcare).")


@app.command()
def embed() -> None:
    """Embed items missing vectors (fastembed)."""
    conn, settings = _connect()
    dbm.init_db(conn)
    n = run_embed(conn, settings)
    conn.close()
    console.print(f"[green]Embedded {n} items.[/green]")


@app.command("llm-screen")
def llm_screen_cmd(
    force: bool = typer.Option(False, "--force", "-f", help="Re-run LLM for all eligible rows"),
) -> None:
    """OpenAI JSON classify: tool opportunity vs news / other (requires IDEAS_OPENAI_API_KEY)."""
    conn, settings = _connect()
    dbm.init_db(conn)
    if not llm_screen_enabled(settings):
        console.print(
            "[red]Set OPENAI_API_KEY (default provider) or GEMINI_API_KEY with IDEAS_LLM_PROVIDER=gemini[/red]"
        )
        parsed_names = list(parse_bare_api_keys_from_dotenv_files().keys())
        env_paths = discover_dotenv_paths()
        console.print(f"[dim]CWD:[/dim] {Path.cwd()}")
        console.print(f"[dim].env files used:[/dim] {len(env_paths)}")
        for p in env_paths[:6]:
            console.print(f"  • {p}")
        if len(env_paths) > 6:
            console.print("  • …")
        console.print(
            f"[dim]Bare key names found in those files:[/dim] {parsed_names or '(none) — check save on disk, variable name, non-empty value)'}"
        )
        raise typer.Exit(code=1)
    n = run_llm_screen(conn, settings, force=force)
    conn.close()
    console.print(f"[green]LLM screening updated {n} rows.[/green]")


@app.command()
def cluster() -> None:
    """Assign items to clusters (sequential cosine threshold)."""
    conn, settings = _connect()
    dbm.init_db(conn)
    n = rebuild_clusters(conn, settings)
    conn.close()
    console.print(f"[green]Clustered {n} items.[/green]")
    if n == 0 and llm_screen_enabled(settings):
        console.print(
            "[yellow]No embedded rows passed filters. Run `ideas llm-screen` if items lack llm_tool_score.[/yellow]"
        )


@app.command()
def score() -> None:
    """Compute scores and store snapshots."""
    conn, settings = _connect()
    dbm.init_db(conn)
    scored = compute_cluster_scores(conn, settings)
    persist_snapshots(conn, scored)
    conn.close()
    console.print(f"[green]Scored {len(scored)} clusters.[/green]")


@app.command("report")
def report_cmd(
    top: int = typer.Option(25, "--top", "-n"),
    fmt: str = typer.Option("md", "--format", "-f", help="md | csv"),
    output: Optional[Path] = typer.Option(None, "--output", "-o"),
    compact: bool = typer.Option(
        False,
        "--compact",
        "-c",
        help="Markdown: summary table only (no per-cluster detail section).",
    ),
    detail_limit: int = typer.Option(
        15,
        "--detail-limit",
        help="Markdown: max clusters in the detail section (ignored with --compact).",
    ),
) -> None:
    """Print ranked themes."""
    conn, settings = _connect()
    dbm.init_db(conn)
    scored = compute_cluster_scores(conn, settings)
    conn.close()

    if not scored:
        console.print("[yellow]No clusters yet — run ingest, embed, cluster first.[/yellow]")
        raise typer.Exit(0)

    if fmt == "csv":
        sio = io.StringIO()
        report_csv(scored, top, sio)
        data = sio.getvalue()
        if output:
            output.write_text(data, encoding="utf-8")
        else:
            sys.stdout.write(data)
        return

    md = report_markdown(scored, top, compact=compact, detail_limit=detail_limit)
    if output:
        output.write_text(md, encoding="utf-8")
    else:
        sys.stdout.write(md)


@app.command()
def run(
    top: int = typer.Option(25, "--top", "-n"),
) -> None:
    """ingest → embed → cluster → score → report"""
    n, nh = _ingest_impl("hn-stackexchange")
    console.print(f"[green]Upserted {n} items[/green] ({nh} flagged healthcare).")

    conn, settings = _connect()
    dbm.init_db(conn)
    ne = run_embed(conn, settings)
    conn.close()
    console.print(f"[green]Embedded {ne} items.[/green]")

    if llm_screen_enabled(settings):
        conn, settings = _connect()
        dbm.init_db(conn)
        n_llm = run_llm_screen(conn, settings, force=False)
        conn.close()
        console.print(f"[green]LLM screening touched {n_llm} rows.[/green]")

    conn, settings = _connect()
    dbm.init_db(conn)
    nc = rebuild_clusters(conn, settings)
    conn.close()
    console.print(f"[green]Clustered {nc} items.[/green]")

    conn, settings = _connect()
    dbm.init_db(conn)
    scored = compute_cluster_scores(conn, settings)
    persist_snapshots(conn, scored)
    conn.close()
    console.print(f"[green]Scored {len(scored)} clusters.[/green]")

    if not scored:
        console.print("[yellow]No clusters to report.[/yellow]")
        return

    sys.stdout.write(report_markdown(scored, top))


def main() -> None:
    app()


if __name__ == "__main__":
    main()
