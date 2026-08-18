# CockroachDB Cloud Managed MCP Server Setup

**Status as of 2026-08-18:** the CockroachDB Cloud cluster exists and the MCP
server was registered locally, but the interactive browser authorization was
not completed. The Devpost submission therefore does not claim the Managed MCP
Server as one of its two CockroachDB tools.

Endpoint: `https://cockroachlabs.cloud/mcp` (HTTPS transport), per the Cockroach Labs quickstart:
https://www.cockroachlabs.com/docs/cockroachcloud/connect-to-the-cockroachdb-cloud-mcp-server

## Setup steps

1. Create or reuse a CockroachDB Cloud cluster and note its cluster ID.
2. Add the server to a supported agent session with the CLI:

   ```
   claude mcp add cockroachdb-cloud https://cockroachlabs.cloud/mcp --transport http --header "mcp-cluster-id: {your-cluster-id}"
   ```

   Equivalent manual configuration, in the `mcpServers` section of the client config:

   ```json
   "cockroachdb-cloud": {
     "type": "http",
     "url": "https://cockroachlabs.cloud/mcp",
     "headers": {
       "mcp-cluster-id": "{your-cluster-id}"
     }
   }
   ```

3. Authorize the connection: run `claude /mcp`, select `cockroachdb-cloud`,
   complete the browser login and organization selection, and grant access via
   the "Authorize MCP Access" prompt. This is the remaining step for Recant.

## Read-only policy

The Managed MCP Server itself exposes both read tools (queries, schema inspection, cluster info) and write tools (creating databases/tables, inserting rows). Per spec section 10, this project restricts itself to the read tools only during development (schema inspection and query-plan analysis); any actual write path always goes through the attest-gateway, never through MCP, even in dev. In the product, the Investigator agent also only ever issues read-only forensic queries through MCP.

## Audit log

MCP tool calls against the cluster are audit-logged by CockroachDB Cloud. Recant
does not yet have a captured MCP audit record, so no such record appears in the
submission video. The separate read-only `ccloud` preflight used by the
submission lives at `ops/inspect_cloud_cluster.sh`.
