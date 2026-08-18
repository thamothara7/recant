#!/usr/bin/env bash
set -euo pipefail

# Read-only submission and operations preflight for the agent-ready ccloud CLI.
# The output intentionally excludes cluster ids, SQL hosts, account ids, and
# creator ids so it is safe to paste into a build log or judging evidence.

cluster_name="${RECANT_CCLOUD_CLUSTER:-recant}"
expected_provider="${RECANT_CCLOUD_PROVIDER:-AWS}"
expected_region="${RECANT_CCLOUD_REGION:-us-east-1}"

for command_name in ccloud jq; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "required command not found: $command_name" >&2
    exit 1
  fi
done

cluster_json="$(ccloud -q cluster info "$cluster_name" -o json)"

if ! jq -e \
  --arg name "$cluster_name" \
  --arg provider "$expected_provider" \
  --arg region "$expected_region" \
  '.name == $name
   and .state == "CREATED"
   and .cloud_provider == $provider
   and ([.regions[].name] | index($region) != null)' \
  <<<"$cluster_json" >/dev/null; then
  echo "cluster '$cluster_name' is not ready on $expected_provider in $expected_region" >&2
  exit 1
fi

jq '
  {
      name,
      state,
      plan,
      cloud_provider,
      regions: [.regions[].name],
      cockroach_version
    }
' <<<"$cluster_json"
