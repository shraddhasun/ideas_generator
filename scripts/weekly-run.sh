#!/usr/bin/env bash
# Weekly pipeline: ingest all configured sources, last ~7 days, full report.
# Schedule with cron, e.g. Monday 06:00 —  0 6 * * 1  /path/to/weekly-run.sh >> /path/to/weekly.log 2>&1
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ -f ".venv/bin/activate" ]]; then
  # shellcheck source=/dev/null
  source ".venv/bin/activate"
fi
export PATH="${ROOT}/.venv/bin:${PATH}"
exec ideas run -s all --top 50 -o "${ROOT}/report.md"
