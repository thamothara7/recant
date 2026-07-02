#!/usr/bin/env bash
# Proof moment 6: kill a node mid-query; the survivors keep answering.
set -euo pipefail
node="${1:?usage: kill-node.sh <1|2|3>}"
cd "$(dirname "$0")"

docker compose kill "roach${node}"
echo "roach${node} is down. Forensics queries against ports 26257-26259 (minus the dead node) still answer."
