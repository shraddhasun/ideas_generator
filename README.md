# Ideas generator

Ingests **Hacker News**, **Stack Exchange**, and **dev.to** on the default `ideas ingest`, filters out healthcare-related content, **scores each post for “business tool opportunity”** (embedding similarity to a fixed anchor describing B2B / ops problems solvable with software), then clusters and ranks only posts above **`IDEAS_MIN_BUSINESS_TOOL_FIT`**. **RSS** (default includes **Lobsters**), **GitLab** issues, **Discourse** topics, **Mastodon** hashtags, and **Lemmy** posts use **public APIs** (no key by default). **Reddit**, **Product Hunt**, and optional tokens for **GitHub / dev.to / GitLab** improve limits or private access (see below).

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

Other sources:

```bash
ideas ingest -s hn              # Hacker News only
ideas ingest -s stackexchange   # Stack Exchange only
ideas ingest -s all               # Everything below when configured (+ RSS Lobsters by default)
ideas ingest -s reddit            # Reddit only (requires credentials)
ideas ingest -s product-hunt    # Product Hunt only (requires IDEAS_PRODUCT_HUNT_TOKEN)
ideas ingest -s github          # GitHub issues only (requires IDEAS_GITHUB_REPOS)
ideas ingest -s devto           # dev.to recent articles only (no API key)
ideas ingest -s rss             # RSS feeds only (uses IDEAS_RSS_FEED_URLS; default is Lobsters)
ideas ingest -s gitlab          # GitLab issues (set IDEAS_GITLAB_PROJECTS)
ideas ingest -s discourse       # Discourse /latest.json (set IDEAS_DISCOURSE_BASE_URLS)
ideas ingest -s mastodon        # Mastodon hashtag timelines (host + hashtags)
ideas ingest -s lemmy           # Lemmy post list (set IDEAS_LEMMY_HOST)
```

Default **`ideas ingest`** includes HN, SE, and dev.to. **`ideas ingest -s all`** adds optional Reddit, Product Hunt, GitHub, **RSS** (defaults to **`https://lobste.rs/h.rss`** unless you override **`IDEAS_RSS_FEED_URLS`**), GitLab, Discourse, Mastodon, and Lemmy when the corresponding env vars are set.

Or one shot:

```bash
ideas run --top 25              # default ingest: all (HN+SE + optional sources)
ideas run -s hn-stackexchange   # HN + SE only
```

Data lives in `./data/ideas.sqlite3` by default (gitignored).

- **`IDEAS_MIN_BUSINESS_TOOL_FIT`** (default ~`0.48`): cosine vs anchor; **lower** lets more through (including newsy HN), **higher** keeps only stronger “niche B2B / operational tool” matches. Set to **`0`** to disable this gate (legacy behavior).
- **`IDEAS_BUSINESS_TOOL_ANCHOR`**: optional env override for the anchor paragraph (otherwise uses the built-in default in `config.py`).
- Lower **`IDEAS_CLUSTER_SIMILARITY_THRESHOLD`** (e.g. `0.72`) to merge more posts into fewer, broader themes; raise it (default ~`0.80`) for stricter, smaller clusters.
- Adjust **`IDEAS_HN_LOOKBACK_SECONDS`** to control how far back HN pulls stories (default: 7 days).

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

### Product Hunt (optional)

Register a developer token via the [Product Hunt API docs](https://api.producthunt.com/v2/docs), set **`IDEAS_PRODUCT_HUNT_TOKEN`** (or **`PRODUCT_HUNT_TOKEN`**), then use **`ideas ingest -s all`** or **`-s product-hunt`**. **`IDEAS_PRODUCT_HUNT_POSTS_LIMIT`** caps ranked launches (default 50).

### GitHub (optional)

Set **`IDEAS_GITHUB_REPOS`** to comma-separated **`owner/repo`** pairs. Fetches **recent open issues** (not pull requests). **`IDEAS_GITHUB_TOKEN`** (or **`GITHUB_TOKEN`**) is optional for public repos but improves rate limits. Tune **`IDEAS_GITHUB_ISSUES_PER_REPO`** (default 25).

### Reddit (optional)

Create an app at [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps), then set **`IDEAS_REDDIT_CLIENT_ID`**, **`IDEAS_REDDIT_CLIENT_SECRET`**, and **`IDEAS_REDDIT_USER_AGENT`** in `.env`. Use **`ideas ingest -s all`** or **`-s reddit`**.

## Tests

```bash
pytest
```

## Legal

Use official APIs; respect rate limits and each platform’s terms. Reddit OAuth, Product Hunt tokens, and GitHub API access are subject to each provider’s policies.
