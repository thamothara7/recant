#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

docker compose up -d
sleep 3
docker compose exec roach1 ./cockroach init --insecure --host=roach1:26257 2>/dev/null || true

attempts=0
max_attempts=60
until docker compose exec roach1 ./cockroach sql --insecure --host=roach1:26257 \
    -e "SELECT 1" >/dev/null 2>&1; do
    attempts=$((attempts + 1))
    if [ "$attempts" -ge "$max_attempts" ]; then
        echo "cluster failed to reach ready state after $max_attempts seconds" >&2
        echo "for debugging, try: docker compose logs roach1" >&2
        exit 1
    fi
    sleep 1
done

# SET CLUSTER SETTING cannot run in a multi-statement transaction: keep the
# statements in separate -e flags so each runs as its own implicit transaction.
docker compose exec roach1 ./cockroach sql --insecure --host=roach1:26257 \
    -e "CREATE DATABASE IF NOT EXISTS recant" \
    -e "SET CLUSTER SETTING kv.rangefeed.enabled = true"

echo "cluster ready: postgresql://root@localhost:26257/recant?sslmode=disable"
