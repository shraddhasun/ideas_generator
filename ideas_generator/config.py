from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Directory containing the `ideas_generator` package (…/ideas_generator/ideas_generator).
_PKG_DIR = Path(__file__).resolve().parent
# Project/layout root when installed editable (parent of package dir).
_PACKAGE_LAYOUT_ROOT = _PKG_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="IDEAS_",
        # Prefer project .env next to package; overridden by explicit paths in get_settings via parsing.
        env_file=_PACKAGE_LAYOUT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_path: Path = Field(default=Path("data/ideas.sqlite3"))
    embedding_model: str = Field(default="BAAI/bge-small-en-v1.5")
    cluster_similarity_threshold: float = Field(default=0.80, ge=0.0, le=1.0)

    reddit_client_id: str | None = None
    reddit_client_secret: str | None = None
    reddit_user_agent: str = "ideas-generator/0.1"
    reddit_subreddits: str = Field(
        default="smallbusiness,sysadmin,accounting,ecommerce,entrepreneur"
    )

    stackexchange_sites: str = Field(default="workplace,softwareengineering,serverfault")

    hn_lookback_seconds: int = Field(default=86400 * 7, description="How far back to search HN stories")

    product_hunt_token: str | None = None
    product_hunt_posts_limit: int = Field(default=50, ge=1, le=100)

    github_token: str | None = None
    github_repos: str = Field(
        default="",
        description="Comma-separated owner/repo pairs for recent open issues (e.g. vercel/next.js)",
    )
    github_issues_per_repo: int = Field(default=25, ge=1, le=100)

    devto_token: str | None = Field(
        default=None,
        description="Optional dev.to API key (higher rate limits); https://dev.to/settings/extensions",
    )
    devto_articles_limit: int = Field(
        default=30,
        ge=1,
        le=1000,
        description="Recent articles from dev.to API (public; optional IDEAS_DEVTO_TOKEN)",
    )
    rss_feed_urls: str = Field(
        default="https://lobste.rs/h.rss",
        description="Comma-separated RSS/Atom URLs (no key); default Lobsters homepage",
    )
    rss_max_entries_per_feed: int = Field(default=25, ge=1, le=200)

    gitlab_token: str | None = Field(default=None, description="Optional GitLab token (rate limits / private)")
    gitlab_host: str = Field(default="https://gitlab.com", description="GitLab API base URL")
    gitlab_projects: str = Field(
        default="",
        description="Comma-separated namespace/project paths on gitlab_host (public API, no token required)",
    )
    gitlab_issues_per_project: int = Field(default=20, ge=1, le=100)

    discourse_base_urls: str = Field(
        default="",
        description="Comma-separated Discourse forum origins, e.g. https://meta.discourse.org",
    )
    discourse_topics_per_site: int = Field(default=25, ge=1, le=100)

    mastodon_host: str = Field(default="", description="Instance host without scheme, e.g. mastodon.social")
    mastodon_hashtags: str = Field(
        default="",
        description="Comma-separated hashtags (no #) for public tag timelines",
    )
    mastodon_limit: int = Field(default=40, ge=1, le=80)

    lemmy_host: str = Field(default="", description="Lemmy instance host, e.g. lemmy.ml")
    lemmy_community: str = Field(
        default="",
        description="Optional community name on that instance (e.g. asklemmy)",
    )
    lemmy_limit: int = Field(default=25, ge=1, le=50)

    weight_recurrence: float = 1.0
    weight_recency: float = 0.5
    weight_engagement: float = 0.3
    weight_cross_platform: float = 0.4
    weight_severity: float = 0.25
    weight_wtp: float = 0.2

    recency_half_life_days: float = 3.0

    min_business_tool_fit: float = Field(
        default=0.48,
        ge=0.0,
        le=1.0,
        description="Cosine vs anchor; below = excluded from clustering/report",
    )
    business_tool_anchor: str = Field(
        default=(
            "A concrete, preferably specific operational or commercial pain in a business context: "
            "named workflows, integrations between systems, revenue ops, finance close, procurement, "
            "IT and security for organizations, compliance and audit, support and customer success at scale, "
            "data pipelines, or buying and renewing B2B / SaaS tools. Prefer niche or vertical angles—"
            "a particular role, stack, or regulation—over generic 'startups should…' advice. "
            "Something a small product team could plausibly own as software, automation, or a narrow platform. "
            "Not: general news, crypto/speculation, pure hiring chatter, games, consumer hobbies, or politics "
            "without a clear business process or buyer pain."
        ),
        description="Embedded once per run; tune to sharpen 'tool for businesses' relevance",
    )

    llm_provider: Literal["openai", "gemini"] = "openai"
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.0-flash"
    llm_min_tool_score: float = Field(
        default=0.60,
        ge=0.0,
        le=1.0,
        description="Include in clusters only if model score >= this (when API key set)",
    )
    llm_screen_min_embed_fit: float = Field(
        default=0.35,
        ge=0.0,
        le=1.0,
        description="Skip LLM calls when embedding business_tool_fit is below this; stamp as skipped_low_embed",
    )
    llm_max_items_per_run: int = Field(
        default=0,
        ge=0,
        description="Cap LLM calls per ideas llm-screen (0 = no cap)",
    )
    llm_sleep_seconds: float = Field(default=0.12, ge=0.0, description="Pause between API calls")

    @model_validator(mode="before")
    @classmethod
    def _standard_env_api_keys(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        o = data.get("openai_api_key")
        if o is None or (isinstance(o, str) and not o.strip()):
            v = os.environ.get("OPENAI_API_KEY") or os.environ.get("IDEAS_OPENAI_API_KEY")
            if v and str(v).strip():
                data["openai_api_key"] = str(v).strip()
        g = data.get("gemini_api_key")
        if g is None or (isinstance(g, str) and not g.strip()):
            v = os.environ.get("GEMINI_API_KEY") or os.environ.get("IDEAS_GEMINI_API_KEY")
            if v and str(v).strip():
                data["gemini_api_key"] = str(v).strip()
        gh = data.get("github_token")
        if gh is None or (isinstance(gh, str) and not gh.strip()):
            v = os.environ.get("GITHUB_TOKEN") or os.environ.get("IDEAS_GITHUB_TOKEN")
            if v and str(v).strip():
                data["github_token"] = str(v).strip()
        ph = data.get("product_hunt_token")
        if ph is None or (isinstance(ph, str) and not ph.strip()):
            v = os.environ.get("PRODUCT_HUNT_TOKEN") or os.environ.get("IDEAS_PRODUCT_HUNT_TOKEN")
            if v and str(v).strip():
                data["product_hunt_token"] = str(v).strip()
        dt = data.get("devto_token")
        if dt is None or (isinstance(dt, str) and not dt.strip()):
            v = os.environ.get("DEVTO_API_KEY") or os.environ.get("IDEAS_DEVTO_TOKEN")
            if v and str(v).strip():
                data["devto_token"] = str(v).strip()
        gl = data.get("gitlab_token")
        if gl is None or (isinstance(gl, str) and not gl.strip()):
            v = os.environ.get("GITLAB_TOKEN") or os.environ.get("IDEAS_GITLAB_TOKEN")
            if v and str(v).strip():
                data["gitlab_token"] = str(v).strip()
        return data


_BARE_KEY_NAMES = frozenset(
    {
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "IDEAS_OPENAI_API_KEY",
        "IDEAS_GEMINI_API_KEY",
    }
)


def discover_dotenv_paths() -> list[Path]:
    """`.env` candidates: layout root, CWD, then parents of CWD (non-editable installs miss layout root)."""
    paths: list[Path] = []
    if env_root := os.environ.get("IDEAS_PROJECT_ROOT"):
        p = Path(env_root).expanduser().resolve()
        if (p / ".env").is_file():
            paths.append(p / ".env")

    layout = _PACKAGE_LAYOUT_ROOT
    if (layout / ".env").is_file():
        paths.append((layout / ".env").resolve())

    cwd = Path.cwd().resolve()
    cur: Path | None = cwd
    for _ in range(14):
        envp = cur / ".env"
        if envp.is_file():
            paths.append(envp.resolve())
        if cur.parent == cur:
            break
        cur = cur.parent

    seen: set[Path] = set()
    uniq: list[Path] = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


def _parse_one_env_file_manual(path: Path) -> dict[str, str]:
    """Fallback when `dotenv_values` is unavailable or returns nothing."""
    out: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        return out
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if key not in _BARE_KEY_NAMES:
            continue
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        if val:
            out[key] = val
    return out


def _parse_one_env_file(path: Path) -> dict[str, str]:
    """Prefer python-dotenv (handles BOM, quoting, encodings)."""
    out: dict[str, str] = {}
    try:
        from dotenv import dotenv_values
    except ImportError:
        return _parse_one_env_file_manual(path)

    data: dict[str, str | None] | None = None
    for enc in ("utf-8-sig", "utf-8"):
        try:
            raw = dotenv_values(path, encoding=enc)
            if isinstance(raw, dict):
                data = raw
                break
        except (UnicodeDecodeError, OSError):
            continue
    if not isinstance(data, dict):
        return _parse_one_env_file_manual(path)

    for k in _BARE_KEY_NAMES:
        v = data.get(k)
        if v is not None and str(v).strip():
            out[k] = str(v).strip()
    if out:
        return out
    return _parse_one_env_file_manual(path)


def parse_bare_api_keys_from_dotenv_files() -> dict[str, str]:
    """Last file in discovery order wins per key."""
    merged: dict[str, str] = {}
    for path in discover_dotenv_paths():
        merged.update(_parse_one_env_file(path))
    return merged


def _hydrate_os_environ_from_parsed(parsed: dict[str, str]) -> None:
    for k, v in parsed.items():
        os.environ[k] = v


def get_settings() -> Settings:
    parsed = parse_bare_api_keys_from_dotenv_files()
    _hydrate_os_environ_from_parsed(parsed)

    try:
        from dotenv import load_dotenv

        for path in discover_dotenv_paths():
            load_dotenv(path, override=True)
    except ImportError:
        pass

    s = Settings()
    upd: dict[str, str] = {}
    if not (s.openai_api_key or "").strip():
        v = parsed.get("OPENAI_API_KEY") or parsed.get("IDEAS_OPENAI_API_KEY")
        if v:
            upd["openai_api_key"] = v
    if not (s.gemini_api_key or "").strip():
        v = parsed.get("GEMINI_API_KEY") or parsed.get("IDEAS_GEMINI_API_KEY")
        if v:
            upd["gemini_api_key"] = v
    if upd:
        s = s.model_copy(update=upd)
    return s


# Backwards compatibility for imports
_REPO_ROOT = _PACKAGE_LAYOUT_ROOT
