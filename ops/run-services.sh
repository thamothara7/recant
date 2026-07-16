#!/usr/bin/env bash
# Start the three Recant services together in one terminal. Ctrl+C stops all
# three. Each is an independent FastAPI app; this is just a convenience launcher
# so you do not need three terminals or to remember DATABASE_URL.
#
#   bash ops/run-services.sh
#
# gateway :8000 (writes)  quarantine :8001 (recant)  forensics :8002 (reads)
set -euo pipefail

# Run from the repo root (the uvicorn module paths and pythonpath="." need it)
# and load .env so DATABASE_URL and friends do not have to be re-exported in
# every new shell. An already-exported DATABASE_URL still wins.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    . ./.env
    set +a
fi

: "${DATABASE_URL:?not set and no .env found; export DATABASE_URL first (see the README quickstart)}"
# Let the console read the judge-overlay header cross-origin in dev.
export RECANT_CORS_ORIGINS="${RECANT_CORS_ORIGINS:-http://localhost:5173}"

# Pre-flight: fail with one clear message instead of three uvicorn bind errors.
BUSY=$(lsof -nP -ti :8000 -ti :8001 -ti :8002 2>/dev/null || true)
if [ -n "$BUSY" ]; then
    echo "ports 8000/8001/8002 are already in use (pids: $(echo "$BUSY" | tr '\n' ' '))." >&2
    echo "probably an earlier launch; stop it with:  pkill -f 'uvicorn services'" >&2
    exit 1
fi

pids=()
uv run uvicorn services.attest_gateway.app:app --port 8000 & pids+=("$!")
uv run uvicorn services.quarantine.app:app     --port 8001 & pids+=("$!")
uv run uvicorn services.forensics.app:app      --port 8002 & pids+=("$!")

trap 'kill "${pids[@]}" 2>/dev/null || true' INT TERM
echo "gateway :8000  quarantine :8001  forensics :8002   (Ctrl+C to stop all)"
wait
