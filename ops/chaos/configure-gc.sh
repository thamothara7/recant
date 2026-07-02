#!/usr/bin/env bash
# Keep 24h of MVCC history on beliefs for AS OF SYSTEM TIME forensics
# (spec section 6). Self-hosted only; Cloud Basic zone config support is
# recorded in docs/spike-changefeeds.md.
set -euo pipefail
cd "$(dirname "$0")"

docker compose exec roach1 ./cockroach sql --insecure --host=roach1:26257 \
    -e "ALTER TABLE recant.beliefs CONFIGURE ZONE USING gc.ttlseconds = 86400;"
echo "beliefs gc.ttlseconds set to 86400"
