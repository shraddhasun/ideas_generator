# Ideas generator

Ingests **Hacker News**, **Stack Exchange**, and **dev.to** on the default `ideas ingest`, filters out healthcare-related content, **scores each post for “business tool opportunity”** (embedding similarity to a fixed anchor describing B2B / ops problems solvable with software), then clusters and ranks only posts above **`IDEAS_MIN_BUSINESS_TOOL_FIT`**. **RSS** (default includes **Lobsters**), **GitLab** issues, **Discourse** topics, **Mastodon** hashtags, and **Lemmy** posts use **public APIs** (no key by default). **Reddit** and optional tokens for **GitHub / dev.to / GitLab** improve limits or private access (see below).

## Setup

```bash
cd ideas_generator
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

No API keys are required for the default flow (HN + Stack Exchange + dev.to). An optional **`IDEAS_DEVTO_TOKEN`** improves dev.to rate limits (create under **dev.to → Settings → Extensions**).

## Usage

```bash
ideas init-db
ideas ingest                    # default: HN + Stack Exchange + dev.to
ideas embed
ideas cluster
ideas score
ideas report --top 25
```

Optional **devtools / PM–design–engineering** lens (last 90 days; writes `devtools_report.md`, gitignored like `report.md`):

```bash
python3 -m ideas_generator.devtools_report
```

Other sources:

```bash
ideas ingest -s hn              # Hacker News only
ideas ingest -s stackexchange   # Stack Exchange only
ideas ingest -s all               # Everything below when configured (+ RSS Lobsters by default)
ideas ingest -s reddit            # Reddit only (requires credentials)
ideas ingest -s github          # GitHub issues only (requires IDEAS_GITHUB_REPOS)
ideas ingest -s devto           # dev.to recent articles only (no API key)
ideas ingest -s rss             # RSS feeds only (uses IDEAS_RSS_FEED_URLS; default is Lobsters)
ideas ingest -s gitlab          # GitLab issues (set IDEAS_GITLAB_PROJECTS)
ideas ingest -s discourse       # Discourse /latest.json (set IDEAS_DISCOURSE_BASE_URLS)
ideas ingest -s mastodon        # Mastodon hashtag timelines (host + hashtags)
ideas ingest -s lemmy           # Lemmy post list (set IDEAS_LEMMY_HOST)
```

Default **`ideas ingest`** includes HN, SE, and dev.to. **`ideas ingest -s all`** adds optional Reddit, GitHub, **RSS** (defaults to **`https://lobste.rs/h.rss`** unless you override **`IDEAS_RSS_FEED_URLS`**), GitLab, Discourse, Mastodon, and Lemmy when the corresponding env vars are set.

Or one shot:

```bash
ideas run --top 25              # default ingest: all (HN+SE + optional sources)
ideas run -s hn-stackexchange   # HN + SE only
ideas run -s all --top 50 -o report.md   # full run, write Markdown to file (good for cron)
```

Data lives in `./data/ideas.sqlite3` by default (gitignored).

- **`IDEAS_MIN_BUSINESS_TOOL_FIT`** (default ~`0.48`): cosine vs anchor; **lower** lets more through (including newsy HN), **higher** keeps only stronger “niche B2B / operational tool” matches. Set to **`0`** to disable this gate (legacy behavior).
- **`IDEAS_BUSINESS_TOOL_ANCHOR`**: optional env override for the anchor paragraph (otherwise uses the built-in default in `config.py`).
- Lower **`IDEAS_CLUSTER_SIMILARITY_THRESHOLD`** (e.g. `0.72`) to merge more posts into fewer, broader themes; raise it (default ~`0.80`) for stricter, smaller clusters.
- **`IDEAS_INGEST_LOOKBACK_SECONDS`** (default **`604800`** = 7 days): HN Algolia search window and **post-filter for every source**—only items with `created_at` in the last *N* seconds (UTC) are kept. Set to **`0`** to disable this time filter. **`IDEAS_HN_LOOKBACK_SECONDS`** is deprecated but still honored if set (it overrides the ingest value for the whole window).

### Scheduling (weekly)

The defaults match a **once-a-week** job that pulls roughly the **last 7 days** from each configured source.

1. Ensure **`.env`** lists every API you want (`ideas ingest -s all` skips missing keys with a dim message).
2. Run **`ideas run -s all --top 50 -o report.md`** (or use **`scripts/weekly-run.sh`**, which does the same from the repo root).
3. **Cron** (example: Mondays 06:00 local time):  
   `0 6 * * 1 cd /path/to/ideas_generator && ./scripts/weekly-run.sh >> weekly.log 2>&1`
4. **GitHub Actions** — optional scheduled workflow: **`.github/workflows/weekly-ideas.yml`** (uploads **`report.md`** as an artifact; add repository **secrets** for keys you need).

### Niche B2B discovery (sources)

Generic idea lists come from **broad** inputs. For problems that feel more **specific than ChatGPT**, bias ingestion toward **communities where buyers and operators post**:

- **Stack Exchange** — Set **`IDEAS_STACKEXCHANGE_SITES`** to vertical or ops sites (for example `workplace`, `serverfault`, `dba`, `salesforce`, `sharepoint`, `webmasters`) instead of only general programming Q&A.
- **Reddit** — Expand **`IDEAS_REDDIT_SUBREDDITS`** with the industries you care about (for example `msp`, `sysadmin`, `accounting`, `ecommerce`, `smallbusiness`); requires Reddit API credentials.
- **Discourse** — Point **`IDEAS_DISCOURSE_BASE_URLS`** at vendor or professional forums that expose public **`/latest.json`** (product communities, open-core tools, trade associations).
- **RSS** — Add **`IDEAS_RSS_FEED_URLS`** entries for **industry newsletters**, **niche blogs**, and **association** feeds—not only large tech aggregators.

Front-page **Hacker News** alone skews newsy; combining it with **Discourse**, **targeted Stack Exchange sites**, and **RSS** surfaces more recurring operational pain.

### Founder validation workflow

Retrieval and clustering beat a one-shot chat answer because outputs are **grounded in real posts**. To decide what to build:

1. **Shortlist** a few high-**composite** clusters (and check **recurrence** columns for repeated pain in the window).
2. **Read originals** — open **10–20 source URLs** from those clusters; use the report’s **verbatim** lines as quotes, not paraphrases.
3. **Triangulate** — skim **job ads** or review sites (e.g. G2/Capterra themes) for the same category; alignment strengthens the signal.
4. **Interview** — run **5–10** short calls with people in that role before committing engineering time.

After upgrading, run **`ideas embed`** once so **`business_tool_fit`** is backfilled for rows that already have embeddings.

### LLM screen (optional, recommended for precision)

Uses **OpenAI** by default or **Google Gemini** if you set **`IDEAS_LLM_PROVIDER=gemini`**.

API keys can be the usual bare names in `.env`: **`OPENAI_API_KEY`** and **`GEMINI_API_KEY`** (also supported: **`IDEAS_OPENAI_API_KEY`**, **`IDEAS_GEMINI_API_KEY`**).

The CLI searches for `.env` next to the package (editable install), in the **current working directory**, and in **parent folders**—so `ideas llm-screen` still finds keys if you run from a subfolder. Override with **`IDEAS_PROJECT_ROOT=/path/to/repo`** if needed.

Use **`pip install -e .`** so the package path stays inside your repo; a plain **`pip install .`** can leave the code in `site-packages` with no project `.env` beside it (parent-directory search still usually fixes this).

**OpenAI (default):** set **`OPENAI_API_KEY`**, optionally **`IDEAS_OPENAI_MODEL`** (`gpt-4o-mini`). Then:

- **`ideas llm-screen`** — classifies each embedded post as **business tool opportunity** vs **news / markets / consumer / other**; stores `tool_opportunity_score` (0–1).
- **`ideas run`** runs **`llm-screen` automatically** after **`embed`** when the chosen provider’s key is set.
- Clustering and reports only keep items with **`llm_tool_score >= IDEAS_LLM_MIN_TOOL_SCORE`** (default `0.60`) when LLM screening is enabled.

**Gemini:** set **`IDEAS_LLM_PROVIDER=gemini`**, **`GEMINI_API_KEY`**, and optionally **`IDEAS_GEMINI_MODEL`** (default `gemini-2.0-flash`).

Embedding scores below **`IDEAS_LLM_SCREEN_MIN_EMBED_FIT`** skip the API call and are stamped as skipped (saves cost).

Use **`ideas llm-screen --force`** to re-classify all eligible rows.

### dev.to and RSS

- **dev.to** — Recent articles via the [public API](https://developers.forem.com/api). Optional **`IDEAS_DEVTO_TOKEN`** (or **`DEVTO_API_KEY`**) sends the `api-key` header for higher rate limits. Tune **`IDEAS_DEVTO_ARTICLES_LIMIT`** (default 30). Included in **`ideas ingest`** (default **`hn-stackexchange`**) and **`ideas ingest -s all`**.
- **RSS / Atom** — Default **`IDEAS_RSS_FEED_URLS`** is **`https://lobste.rs/h.rss`**. Add more comma-separated URLs or set empty to skip RSS in **`all`**. Tune **`IDEAS_RSS_MAX_ENTRIES_PER_FEED`**.

### GitLab (optional, no key for public projects)

**`IDEAS_GITLAB_PROJECTS`** — comma-separated **`namespace/project`** paths on **`IDEAS_GITLAB_HOST`** (default `https://gitlab.com`). **`IDEAS_GITLAB_TOKEN`** / **`GITLAB_TOKEN`** optional. **`ideas ingest -s gitlab`** or **`-s all`**.

### Discourse (optional, no key)

**`IDEAS_DISCOURSE_BASE_URLS`** — comma-separated forum origins (e.g. `https://meta.discourse.org`). Uses public **`/latest.json`**. **`IDEAS_DISCOURSE_TOPICS_PER_SITE`** limits topics per forum.

### Mastodon (optional, no key on most instances)

**`IDEAS_MASTODON_HOST`** (e.g. `mastodon.social`) and **`IDEAS_MASTODON_HASHTAGS`** (comma-separated, no `#`). Public tag timelines: **`/api/v1/timelines/tag/...`**. **`IDEAS_MASTODON_LIMIT`**.

### Lemmy (optional, no key)

**`IDEAS_LEMMY_HOST`** (e.g. `lemmy.ml`). Optional **`IDEAS_LEMMY_COMMUNITY`** (e.g. `asklemmy`). **`IDEAS_LEMMY_LIMIT`**.

### GitHub (optional)

Set **`IDEAS_GITHUB_REPOS`** to comma-separated **`owner/repo`** pairs. Fetches **recent open issues** (not pull requests). **`IDEAS_GITHUB_TOKEN`** (or **`GITHUB_TOKEN`**) is optional for public repos but improves rate limits. Tune **`IDEAS_GITHUB_ISSUES_PER_REPO`** (default 25).

### Reddit (optional)

Create an app at [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps), then set **`IDEAS_REDDIT_CLIENT_ID`**, **`IDEAS_REDDIT_CLIENT_SECRET`**, and **`IDEAS_REDDIT_USER_AGENT`** in `.env`. Use **`ideas ingest -s all`** or **`-s reddit`**.

## Tests

```bash
pytest
```

## Legal

Use official APIs; respect rate limits and each platform’s terms. Reddit OAuth and GitHub API access are subject to each provider’s policies.
