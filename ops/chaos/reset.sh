#!/usr/bin/env bash
# Reset the local chaos cluster from scratch and re-apply the schema.
#
# Use this when the integration suite starts failing with serialization errors
# ("WriteTooOld", "ReadWithinUncertaintyInterval") or "unknown agent" 404s: an
# unlicensed multi-node CockroachDB cluster throttles to 5 concurrent
# transactions after a 7-day grace period, and once throttled, the suite plus
# any running services exceed that limit. Destroying the volumes starts a fresh
# grace period and restores full concurrency.
#
#   bash ops/chaos/reset.sh
#
# Then start the services (bash ops/run-services.sh) and, in another terminal,
# reseed (uv run python ops/seed/seed.py). Stop the services before running the
# destructive integration suite so it has the cluster to itself.
set -euo pipefail

cd "$(dirname "$0")/../.."
export DATABASE_URL="${DATABASE_URL:-postgresql://root@localhost:26257/recant?sslmode=disable}"

# Stop any running Recant services first: resetting the database under a live
# service leaves its connection pool pointing at a dead server (the pool now
# self-heals at checkout, but a clean stop/start is still the tidy path).
if pgrep -f "uvicorn services" >/dev/null 2>&1; then
    echo "stopping running Recant services..."
    pkill -f "uvicorn services" || true
    sleep 1
fi

echo "destroying cluster volumes (resets the concurrency throttle)..."
docker compose -f ops/chaos/docker-compose.yml down -v
bash ops/chaos/init.sh
uv run python -m db.migrate
echo "cluster reset and migrated. next: bash ops/run-services.sh, then seed."
