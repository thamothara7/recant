#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

docker compose up -d
sleep 3
docker compose exec roach1 ./cockroach init --insecure --host=roach1:26257 2>/dev/null || true

until docker compose exec roach1 ./cockroach sql --insecure --host=roach1:26257 \
    -e "SELECT 1" >/dev/null 2>&1; do
    sleep 1
done

# SET CLUSTER SETTING cannot run in a multi-statement transaction: keep the
# statements in separate -e flags so each runs as its own implicit transaction.
docker compose exec roach1 ./cockroach sql --insecure --host=roach1:26257 \
    -e "CREATE DATABASE IF NOT EXISTS recant" \
    -e "SET CLUSTER SETTING kv.rangefeed.enabled = true"

echo "cluster ready: postgresql://root@localhost:26257/recant?sslmode=disable"
