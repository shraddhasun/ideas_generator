# Ideas generator

Ingests **Hacker News** and **Stack Exchange** (default), filters out healthcare-related content, **scores each post for “business tool opportunity”** (embedding similarity to a fixed anchor describing B2B / ops problems solvable with software), then clusters and ranks only posts above **`IDEAS_MIN_BUSINESS_TOOL_FIT`**. Optional **Reddit** when you add API keys.

## Setup

```bash
cd ideas_generator
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

No API keys are required for the default HN + Stack Exchange flow.

## Usage

```bash
ideas init-db
ideas ingest                    # default: HN + Stack Exchange only
ideas embed
ideas cluster
ideas score
ideas report --top 25
```

Other sources:

```bash
ideas ingest -s hn              # Hacker News only
ideas ingest -s stackexchange   # Stack Exchange only
ideas ingest -s all               # HN + SE + Reddit (Reddit only if IDEAS_REDDIT_* are set)
ideas ingest -s reddit            # Reddit only (requires credentials)
```

Or one shot:

```bash
ideas run --top 25
```

Data lives in `./data/ideas.sqlite3` by default (gitignored).

- **`IDEAS_MIN_BUSINESS_TOOL_FIT`** (default ~`0.43`): cosine vs anchor; **lower** lets more through (including newsy HN), **higher** keeps only stronger “build a tool for businesses” matches. Set to **`0`** to disable this gate (legacy behavior).
- **`IDEAS_BUSINESS_TOOL_ANCHOR`**: optional env override for the anchor paragraph (otherwise uses the built-in default in `config.py`).
- Lower **`IDEAS_CLUSTER_SIMILARITY_THRESHOLD`** (e.g. `0.72`) to merge more posts into fewer, broader themes; raise it for stricter grouping.
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
- Clustering and reports only keep items with **`llm_tool_score >= IDEAS_LLM_MIN_TOOL_SCORE`** (default `0.55`) when LLM screening is enabled.

**Gemini:** set **`IDEAS_LLM_PROVIDER=gemini`**, **`GEMINI_API_KEY`**, and optionally **`IDEAS_GEMINI_MODEL`** (default `gemini-2.0-flash`).

Embedding scores below **`IDEAS_LLM_SCREEN_MIN_EMBED_FIT`** skip the API call and are stamped as skipped (saves cost).

Use **`ideas llm-screen --force`** to re-classify all eligible rows.

### Reddit (later)

Create an app at [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps), then set `IDEAS_REDDIT_CLIENT_ID`, `IDEAS_REDDIT_CLIENT_SECRET`, and `IDEAS_REDDIT_USER_AGENT` in `.env`. Use `ideas ingest -s all` or `-s reddit`.

## Tests

```bash
pytest
```

## Legal

Use official APIs; respect rate limits and each platform’s terms. Reddit requires OAuth app credentials.
