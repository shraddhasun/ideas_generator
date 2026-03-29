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
from ideas_generator.connectors.devto import fetch_devto_articles
from ideas_generator.connectors.discourse import fetch_discourse_latest
from ideas_generator.connectors.github_issues import fetch_github_issues
from ideas_generator.connectors.gitlab_issues import fetch_gitlab_issues
from ideas_generator.connectors.hn import fetch_hn_items
from ideas_generator.connectors.lemmy import fetch_lemmy_posts
from ideas_generator.connectors.mastodon import fetch_mastodon_tag_timelines
from ideas_generator.connectors.product_hunt import fetch_product_hunt_items
from ideas_generator.connectors.reddit import fetch_reddit_items
from ideas_generator.connectors.rss_feeds import fetch_rss_feeds
from ideas_generator.connectors.stackexchange import fetch_stackexchange_items
from ideas_generator.embed import run_embed
from ideas_generator.llm_screen import run_llm_screen
from ideas_generator.llm_util import llm_screen_enabled
from ideas_generator.filters import is_healthcare_related
from ideas_generator.ingest_window import filter_items_by_lookback
from ideas_generator.models import RawItem
from ideas_generator.score import compute_cluster_scores, persist_snapshots
from ideas_generator.report import report_csv, report_markdown

app = typer.Typer(no_args_is_help=True, help="Business problem finder pipeline.")
console = Console()


def _connect():
    s = get_settings()
    conn = dbm.connect(s.database_path)
    return conn, s


def _normalize_ingest_source(source: str) -> str:
    s = source.strip().lower().replace("_", "-")
    if s == "producthunt":
        return "product-hunt"
    return s


def _ingest_impl(source: str) -> tuple[int, int]:
    source = _normalize_ingest_source(source)
    conn, settings = _connect()
    dbm.init_db(conn)
    raw: list[RawItem] = []

    fetch_hn = source in ("hn", "hn-stackexchange", "all")
    fetch_se = source in ("stackexchange", "hn-stackexchange", "all")
    fetch_reddit = source in ("reddit", "all")
    fetch_ph = source in ("product-hunt", "all")
    fetch_gh = source in ("github", "all")
    fetch_devto = source in ("devto", "all", "hn-stackexchange")
    fetch_rss = source in ("rss", "all")
    fetch_gitlab = source in ("gitlab", "all")
    fetch_discourse = source in ("discourse", "all")
    fetch_mastodon = source in ("mastodon", "all")
    fetch_lemmy = source in ("lemmy", "all")

    lb = settings.effective_ingest_lookback_seconds()
    # HN Algolia requires a positive created_at_i window; when lookback is 0 (no filter), fetch broadly.
    hn_fetch_seconds = lb if lb > 0 else 86400 * 365
    if fetch_hn:
        console.print("Fetching Hacker News…")
        raw.extend(fetch_hn_items(hn_fetch_seconds))

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

    if fetch_ph:
        tok = (settings.product_hunt_token or "").strip()
        if tok:
            console.print("Fetching Product Hunt…")
            raw.extend(
                fetch_product_hunt_items(tok, limit=settings.product_hunt_posts_limit)
            )
        elif source == "product-hunt":
            console.print(
                "[red]Product Hunt requires IDEAS_PRODUCT_HUNT_TOKEN (or PRODUCT_HUNT_TOKEN) in .env[/red]"
            )
            raise typer.Exit(code=1)
        elif source == "all":
            console.print("[dim]Skipping Product Hunt (set IDEAS_PRODUCT_HUNT_TOKEN).[/dim]")

    if fetch_gh:
        gh_repos = [x.strip() for x in settings.github_repos.split(",") if x.strip()]
        if gh_repos:
            console.print(f"Fetching GitHub issues ({len(gh_repos)} repos)…")
            raw.extend(
                fetch_github_issues(
                    settings.github_token,
                    gh_repos,
                    per_repo=settings.github_issues_per_repo,
                )
            )
        elif source == "github":
            console.print(
                "[red]GitHub requires IDEAS_GITHUB_REPOS (comma-separated owner/repo pairs)[/red]"
            )
            raise typer.Exit(code=1)
        elif source == "all":
            console.print("[dim]Skipping GitHub (set IDEAS_GITHUB_REPOS).[/dim]")

    if fetch_devto:
        console.print("Fetching dev.to…")
        raw.extend(
            fetch_devto_articles(
                settings.devto_token,
                limit=settings.devto_articles_limit,
            )
        )

    if fetch_rss:
        rss_urls = [x.strip() for x in settings.rss_feed_urls.split(",") if x.strip()]
        if rss_urls:
            console.print(f"Fetching RSS feeds ({len(rss_urls)})…")
            raw.extend(
                fetch_rss_feeds(
                    rss_urls,
                    max_per_feed=settings.rss_max_entries_per_feed,
                )
            )
        elif source == "rss":
            console.print(
                "[red]RSS requires IDEAS_RSS_FEED_URLS (comma-separated feed URLs)[/red]"
            )
            raise typer.Exit(code=1)
        elif source == "all":
            console.print("[dim]Skipping RSS (set IDEAS_RSS_FEED_URLS to add feeds).[/dim]")

    if fetch_gitlab:
        gl_projects = [x.strip() for x in settings.gitlab_projects.split(",") if x.strip()]
        if gl_projects:
            console.print(f"Fetching GitLab issues ({len(gl_projects)} projects)…")
            raw.extend(
                fetch_gitlab_issues(
                    settings.gitlab_token,
                    gl_projects,
                    host=settings.gitlab_host,
                    per_project=settings.gitlab_issues_per_project,
                )
            )
        elif source == "gitlab":
            console.print(
                "[red]GitLab requires IDEAS_GITLAB_PROJECTS (namespace/project, comma-separated)[/red]"
            )
            raise typer.Exit(code=1)
        elif source == "all":
            console.print("[dim]Skipping GitLab (set IDEAS_GITLAB_PROJECTS).[/dim]")

    if fetch_discourse:
        d_urls = [x.strip() for x in settings.discourse_base_urls.split(",") if x.strip()]
        if d_urls:
            console.print(f"Fetching Discourse ({len(d_urls)} sites)…")
            raw.extend(
                fetch_discourse_latest(
                    d_urls,
                    topics_per_site=settings.discourse_topics_per_site,
                )
            )
        elif source == "discourse":
            console.print(
                "[red]Discourse requires IDEAS_DISCOURSE_BASE_URLS (comma-separated forum URLs)[/red]"
            )
            raise typer.Exit(code=1)
        elif source == "all":
            console.print("[dim]Skipping Discourse (set IDEAS_DISCOURSE_BASE_URLS).[/dim]")

    if fetch_mastodon:
        m_host = (settings.mastodon_host or "").strip()
        m_tags = [x.strip().lstrip("#") for x in settings.mastodon_hashtags.split(",") if x.strip()]
        if m_host and m_tags:
            console.print(f"Fetching Mastodon ({m_host}, {len(m_tags)} tags)…")
            raw.extend(
                fetch_mastodon_tag_timelines(
                    m_host,
                    m_tags,
                    limit=settings.mastodon_limit,
                )
            )
        elif source == "mastodon":
            console.print(
                "[red]Mastodon requires IDEAS_MASTODON_HOST and IDEAS_MASTODON_HASHTAGS[/red]"
            )
            raise typer.Exit(code=1)
        elif source == "all":
            console.print("[dim]Skipping Mastodon (set IDEAS_MASTODON_HOST and IDEAS_MASTODON_HASHTAGS).[/dim]")

    if fetch_lemmy:
        l_host = (settings.lemmy_host or "").strip()
        if l_host:
            console.print(f"Fetching Lemmy ({l_host})…")
            raw.extend(
                fetch_lemmy_posts(
                    l_host,
                    community_name=settings.lemmy_community,
                    limit=settings.lemmy_limit,
                )
            )
        elif source == "lemmy":
            console.print("[red]Lemmy requires IDEAS_LEMMY_HOST[/red]")
            raise typer.Exit(code=1)
        elif source == "all":
            console.print("[dim]Skipping Lemmy (set IDEAS_LEMMY_HOST).[/dim]")

    before = len(raw)
    raw = filter_items_by_lookback(raw, lb)
    dropped_time = before - len(raw)
    if dropped_time and lb > 0:
        console.print(
            f"[dim]Lookback ({lb}s ≈ {lb // 86400}d): dropped {dropped_time} items older than window.[/dim]"
        )

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
        help=(
            "hn-stackexchange (default: HN+SE+dev.to) | hn | stackexchange | reddit | product-hunt | "
            "github | gitlab | discourse | mastodon | lemmy | devto | rss | all"
        ),
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
    source: str = typer.Option(
        "all",
        "--source",
        "-s",
        help="Ingest source (same as ideas ingest); all = HN+SE+dev.to+optional APIs (RSS/GitLab/…)",
    ),
    output: Optional[Path] = typer.Option(
        None,
        "--output",
        "-o",
        help="Write Markdown report to this file instead of printing it on stdout.",
    ),
) -> None:
    """ingest → embed → cluster → score → report"""
    n, nh = _ingest_impl(source)
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

    md = report_markdown(scored, top)
    if output is not None:
        output.write_text(md, encoding="utf-8")
        console.print(f"[green]Wrote report to {output}[/green]")
    else:
        sys.stdout.write(md)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
