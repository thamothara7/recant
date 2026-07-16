#!/usr/bin/env bash
# Package the two fanout Lambdas (W3 cloud leg, plan section 7).
#
# receiver.zip: webhook -> EventBridge shim. Stdlib + boto3 (in the runtime);
#   fanout/handler.py's psycopg import is annotation-only, so no driver ships.
# consumer.zip: EventBridge -> apply_evictions. Ships psycopg[binary] wheels
#   built for the Lambda arm64 python3.12 runtime via pip's cross-platform
#   resolver; our own fanout/ package rides alongside.
#
# Usage: bash fanout/iac/package.sh   (from the repo root)
set -euo pipefail

cd "$(dirname "$0")/../.."
BUILD=fanout/iac/build
rm -rf "$BUILD"
mkdir -p "$BUILD/receiver/fanout" "$BUILD/consumer"

# --- receiver ---------------------------------------------------------------
cp fanout/__init__.py fanout/handler.py fanout/lambda_entry.py "$BUILD/receiver/fanout/"
(cd "$BUILD/receiver" && zip -qr ../receiver.zip .)

# --- consumer ---------------------------------------------------------------
# typing_extensions pinned explicitly: psycopg's _compat imports it on
# py<3.13 but pip's cross-platform resolve skipped the marker (seen live:
# Lambda ModuleNotFoundError). It is a pure-python wheel; harmless to force.
uv run pip install "psycopg[binary]>=3.2" "typing_extensions>=4.6" \
  --platform manylinux2014_aarch64 \
  --python-version 3.12 \
  --implementation cp \
  --only-binary=:all: \
  --target "$BUILD/consumer" \
  --quiet
mkdir -p "$BUILD/consumer/fanout"
cp fanout/__init__.py fanout/handler.py fanout/consumer_entry.py "$BUILD/consumer/fanout/"

# The cluster CA rides in the zip: CockroachDB Cloud serverless certs chain to
# the cluster CA, not a public root, so sslrootcert=system fails in Lambda
# exactly as it does on macOS (decision 22). The SSM URL points verify-full at
# /var/task/root.crt. Refresh the local copy with:
#   curl "https://cockroachlabs.cloud/clusters/<cluster-id>/cert" > ~/.postgresql/root.crt
CA="$HOME/.postgresql/root.crt"
[ -f "$CA" ] || { echo "cluster CA missing at $CA; download it first (see comment above)" >&2; exit 1; }
cp "$CA" "$BUILD/consumer/root.crt"
(cd "$BUILD/consumer" && zip -qr ../consumer.zip .)

ls -la "$BUILD"/receiver.zip "$BUILD"/consumer.zip
