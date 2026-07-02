# CockroachDB Cloud Managed MCP Server Setup

**Status: blocked on U1** (CockroachDB Cloud signup and cluster creation). These are the steps to run once U1 is complete; nothing here has been executed yet.

Endpoint: `https://cockroachlabs.cloud/mcp` (HTTPS transport), per the Cockroach Labs quickstart:
https://www.cockroachlabs.com/docs/cockroachcloud/connect-to-the-cockroachdb-cloud-mcp-server

## Steps (after U1)

1. Create (or reuse) a CockroachDB Cloud cluster and note its cluster ID.
2. Add the server to this Claude Code session with the CLI:

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

3. Authorize the connection: run `claude /mcp`, select `cockroachdb-cloud`, complete the browser login/organization selection, and grant access via the "Authorize MCP Access" prompt.

## Read-only policy

The Managed MCP Server itself exposes both read tools (queries, schema inspection, cluster info) and write tools (creating databases/tables, inserting rows). Per spec section 10, this project restricts itself to the read tools only during development (schema inspection and query-plan analysis); any actual write path always goes through the attest-gateway, never through MCP, even in dev. In the product, the Investigator agent also only ever issues read-only forensic queries through MCP.

## Audit log

MCP tool calls against the cluster are audit-logged by CockroachDB Cloud. Retrieval of that audit log is done via the `ccloud` CLI (U2) from a script under `ops/`, planned for Week 3 alongside the fanout/eviction work, and is itself shown on camera in the demo video (section 11) as part of the custody story.
