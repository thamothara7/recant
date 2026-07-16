#!/usr/bin/env bash
# Start the three Recant services together in one terminal. Ctrl+C stops all
# three. Each is an independent FastAPI app; this is just a convenience launcher
# so you do not need three terminals.
#
#   export DATABASE_URL=postgresql://root@localhost:26257/recant?sslmode=disable
#   bash ops/run-services.sh
#
# gateway :8000 (writes)  quarantine :8001 (recant)  forensics :8002 (reads)
set -euo pipefail

: "${DATABASE_URL:?export DATABASE_URL first (see the README quickstart)}"
# Let the console read the judge-overlay header cross-origin in dev.
export RECANT_CORS_ORIGINS="${RECANT_CORS_ORIGINS:-http://localhost:5173}"

pids=()
uv run uvicorn services.attest_gateway.app:app --port 8000 & pids+=("$!")
uv run uvicorn services.quarantine.app:app     --port 8001 & pids+=("$!")
uv run uvicorn services.forensics.app:app      --port 8002 & pids+=("$!")

trap 'kill "${pids[@]}" 2>/dev/null || true' INT TERM
echo "gateway :8000  quarantine :8001  forensics :8002   (Ctrl+C to stop all)"
wait
