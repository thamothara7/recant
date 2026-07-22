# Recant

Recant is a provenance and retraction layer for shared agent memory. It records
who wrote each belief, where it came from, and its position in a signed hash
chain. When a source turns out to be unsafe, one `recant(source_id)` call finds
and quarantines the full contamination closure: direct citations, explicit
descendants, and semantically similar copies that have no recorded edge. A
durable outbox then evicts those beliefs from agent working memory and aborts
any pending actions that depended on them.

Recant is not a chatbot or a RAG application. It is the custody and incident
response layer that sits beneath an agent-memory system.

The deployed console is a deterministic fixture demo at
[recant.vercel.app](https://recant.vercel.app). It runs entirely in the browser
and needs no backend.

---

## Table of contents

1. [What is in the repository](#what-is-in-the-repository)
2. [Prerequisites](#prerequisites)
3. [Option A: run only the console (no backend needed)](#option-a-run-only-the-console-no-backend-needed)
4. [Option B: full local stack](#option-b-full-local-stack)
   - [Step 1: clone and configure](#step-1-clone-and-configure)
   - [Step 2: start the database](#step-2-start-the-database)
   - [Step 3: apply the schema](#step-3-apply-the-schema)
   - [Step 4: run the tests](#step-4-run-the-tests)
   - [Step 5: start the services](#step-5-start-the-services)
   - [Step 6: start the eviction worker](#step-6-start-the-eviction-worker)
   - [Step 7: verify everything is up](#step-7-verify-everything-is-up)
   - [Step 8: seed the demo scenario](#step-8-seed-the-demo-scenario)
   - [Step 9: preview and execute a recant](#step-9-preview-and-execute-a-recant)
   - [Step 10: connect the console to the local services](#step-10-connect-the-console-to-the-local-services)
5. [Everyday commands](#everyday-commands)
6. [Service and API reference](#service-and-api-reference)
7. [Integrating an agent](#integrating-an-agent)
8. [Optional features](#optional-features)
9. [Troubleshooting](#troubleshooting)
10. [Safety notes](#safety-notes)
11. [License](#license)

---

## What is in the repository

| Component | Location | What it does |
| --- | --- | --- |
| Attest gateway | `services/attest_gateway/` | The only supported write path. Creates agents and sources, attests beliefs, and maintains each agent's signed hash chain. |
| Quarantine service | `services/quarantine/` | Previews and executes `recant(source_id)` inside a serializable transaction. |
| Forensics API | `services/forensics/` | Read-only board, provenance, custody-chain, incident, evidence, and time-travel queries. |
| Taint engine | `services/taint_engine/` | Traverses explicit derivations and vector similarity matches to compute the contamination closure. |
| Fanout | `fanout/` | Local durable outbox worker and AWS Lambda/EventBridge implementation for eviction. |
| Demo fleet | `fleet/` | Three deterministic agents with CockroachDB-backed working memory. |
| Web console | `console/` | Vite/React UI. Uses fixture data unless live API URLs are configured. |
| Database | `db/migrations/` | Ordered CockroachDB schema migrations. |

---

## Prerequisites

### For the console only (Option A)

- Node.js 20 or newer
- npm (bundled with Node.js)
- Git

### For the full local stack (Option B)

- **Docker Desktop** or Docker Engine with the Compose plugin. It runs the
  three-node local CockroachDB cluster.
- **uv** (https://docs.astral.sh/uv/), which manages the Python version and all
  Python dependencies. You do not need a separate Python installation.
- **Node.js 20+** and npm, for the console only.
- Git.

#### Install on macOS

```bash
brew install --cask docker
brew install uv node git
```

#### Install on Windows

Install Docker Desktop, uv, Node.js, and Git from their official sites, then
run all shell commands inside **WSL 2**. The operational scripts are Bash
scripts and do not run in PowerShell or Command Prompt. After installing, open
Docker Desktop, go to Settings, then Resources, then WSL integration, and
enable it for your WSL distribution. Confirm Docker is accessible from WSL
before continuing:

```bash
docker info
```

---

## Option A: run only the console (no backend needed)

This is the fastest way to see Recant. It uses deterministic fixture data and
does not require Docker, Python, or any running service.

```bash
git clone https://github.com/thamothara7/recant.git
cd recant/console
npm ci
npm run dev
```

Open http://localhost:5173 in your browser. Press Ctrl+C in the terminal to
stop the server.

The console opens in Story mode, which is a five-step guided walkthrough. Use
the Story/Explore toggle in the top bar to switch to Explore mode, where you
can click any belief card to trace its provenance.

---

## Option B: full local stack

These steps bring up a local three-node CockroachDB cluster, install all
dependencies, apply the database schema, run the tests, start the Python
services, seed the demo data, and connect the console.

All commands are run from the repository root unless noted otherwise.

### Step 1: clone and configure

```bash
git clone https://github.com/thamothara7/recant.git
cd recant
cp .env.example .env
uv sync
```

What each command does:

- `git clone` downloads the repository.
- `cp .env.example .env` creates your local configuration file. Git ignores
  `.env`, so credentials you add there are never committed.
- `uv sync` reads `pyproject.toml`, installs the correct Python version, and
  creates a `.venv` directory with all Python dependencies.

The `.env` file that was just created contains default values that work with
the local Docker cluster. The most important variable is:

```
DATABASE_URL=postgresql://root@localhost:26257/recant?sslmode=disable
```

To make these variables available in a shell, run:

```bash
set -a
. ./.env
set +a
```

You need to do this in every new terminal that runs Python commands (migrations,
tests, the worker, the fleet). The services launcher `ops/run-services.sh`
loads `.env` automatically so you do not need to export variables there.

### Step 2: start the database

Make sure Docker Desktop (or Docker Engine) is running before this step. You
can confirm it with `docker info`.

```bash
bash ops/chaos/init.sh
```

This script starts a local three-node CockroachDB cluster using Docker Compose.
It is safe to run more than once; if the cluster is already running it will do
nothing harmful.

When the cluster is ready the script prints:

```
postgresql://root@localhost:26257/recant?sslmode=disable
```

You can also open the CockroachDB admin UI at http://localhost:8080 to see
the cluster state visually.

To check that the containers are running:

```bash
docker compose -f ops/chaos/docker-compose.yml ps
```

### Step 3: apply the schema

This command creates all the tables, indexes, and sequences that Recant needs:

```bash
uv run python -m db.migrate
```

Migrations are tracked. If you run this command again it applies only the
migrations that have not been applied yet, so it is safe to repeat.

### Step 4: run the tests

Before seeding data it is a good idea to confirm the stack works correctly.

Export the environment variables first if you have not done so in this terminal:

```bash
set -a
. ./.env
set +a
```

Then run the full test suite:

```bash
uv run pytest
```

The test suite includes both unit tests (no database needed) and integration
tests (write and delete rows from the local database). Stop any running services
and do not point this at a database you want to keep, because integration tests
delete rows before every test.

To run only the unit tests without a database connection:

```bash
env -u DATABASE_URL uv run pytest tests/unit
```

To run only the integration tests:

```bash
uv run pytest tests/integration
```

You can also confirm the console builds cleanly:

```bash
cd console && npm ci && npm run build && cd ..
```

### Step 5: start the services

Open a dedicated terminal for this step. The services will keep running in this
terminal until you press Ctrl+C.

```bash
bash ops/run-services.sh
```

This starts three FastAPI services in a single terminal:

| Service | URL | Interactive API docs |
| --- | --- | --- |
| Attest gateway | http://localhost:8000 | http://localhost:8000/docs |
| Quarantine service | http://localhost:8001 | http://localhost:8001/docs |
| Forensics API | http://localhost:8002 | http://localhost:8002/docs |

The launcher checks that those ports are free before starting. If a port is
already in use it will print the process IDs and exit. See the
[Troubleshooting](#troubleshooting) section for how to clear a busy port.

### Step 6: start the eviction worker

Open a second dedicated terminal for this step.

```bash
set -a
. ./.env
set +a
uv run python -m fanout.worker --consumer local-evictor
```

This worker polls the database for new `memory_events` rows and processes them.
It is required if you want to see working-memory eviction and action abortion
happen after a recant. Without this worker, beliefs are quarantined in the
database but agents still hold stale copies in their local working memory.

The worker runs continuously until you press Ctrl+C. To drain the current queue
and then exit:

```bash
uv run python -m fanout.worker --consumer local-evictor --once
```

### Step 7: verify everything is up

From a third terminal, check that each service is healthy:

```bash
curl -fsS http://localhost:8000/healthz
curl -fsS http://localhost:8001/healthz
curl -fsS http://localhost:8002/healthz
```

Each command should print `{"status":"ok"}`. If a command hangs or returns an
error, check the services terminal for log output.

### Step 8: seed the demo scenario

Export the environment variables in this terminal:

```bash
set -a
. ./.env
set +a
```

Then run the seeder:

```bash
uv run python ops/seed/seed.py
```

Expected output:

```
seeded 3 agents, 4 sources, 9 beliefs
```

The seeder creates a deterministic contamination scenario: a Research bot
ingests a forum post claiming a 365-day refund window, a Support bot paraphrases
that claim with no link back to the original, and an Ops bot queues a bad
refund action based on the paraphrase.

The seeder will fail with an error if data already exists. This is intentional
so that running it twice does not produce a duplicate story. If you want to
start fresh, reset the local cluster first (this destroys all local data):

```bash
bash ops/chaos/reset.sh
bash ops/chaos/init.sh
uv run python -m db.migrate
```

### Step 9: preview and execute a recant

Find the ID of the untrusted source and preview what a recant would affect
(this does not change any data):

```bash
source_id="$(curl -fsS http://localhost:8002/board | uv run python -c '
import json, sys
print(next(s["source_id"] for s in json.load(sys.stdin)["sources"] if s["trust_tier"] == "untrusted"))
')"

curl -fsS -X POST http://localhost:8001/taint/preview \
  -H 'content-type: application/json' \
  -d "{\"source_id\":\"$source_id\"}" | uv run python -m json.tool
```

The preview response shows the full contamination closure: how many beliefs
would be quarantined and how many agents they belong to.

When you are ready to execute the recant:

```bash
curl -fsS -X POST http://localhost:8001/recant \
  -H 'content-type: application/json' \
  -d "{\"source_id\":\"$source_id\",\"actor\":\"local-operator\"}" | uv run python -m json.tool
```

The response includes an incident ID, the full list of quarantined belief IDs,
and the newly flipped beliefs. The running fanout worker consumes the resulting
`memory_events` row.

Inspect the live board to confirm the status changes:

```bash
curl -fsS http://localhost:8002/board | uv run python -m json.tool
```

### Step 10: connect the console to the local services

The console uses fixture data by default. To point it at the running local
services, pass both service URLs as build-time Vite environment variables:

```bash
cd console
npm ci
VITE_FORENSICS_URL=http://localhost:8002 \
VITE_QUARANTINE_URL=http://localhost:8001 \
  npm run dev
```

Open http://localhost:5173. The console will now show your live local board
instead of the built-in fixture data.

Important notes:

- These are build-time Vite variables. If you change them, stop Vite and
  restart it.
- The console must be served from an origin listed in `RECANT_CORS_ORIGINS`.
  The local default is `http://localhost:5173`. If your browser reports a
  CORS error, check that value in your `.env` file and restart the services.

---

## Everyday commands

| Goal | Command | Notes |
| --- | --- | --- |
| Start database | `bash ops/chaos/init.sh` | Idempotent. Requires Docker. |
| Stop database | `docker compose -f ops/chaos/docker-compose.yml down` | Does not delete data. |
| Reset database | `bash ops/chaos/reset.sh` | Destroys Docker volumes and all data. |
| Apply schema | `uv run python -m db.migrate` | Requires an exported `DATABASE_URL`. Safe to repeat. |
| Start services | `bash ops/run-services.sh` | Starts gateway `:8000`, quarantine `:8001`, forensics `:8002`. |
| Stop services | Ctrl+C in the services terminal | Stops all three services. |
| Start eviction worker | `uv run python -m fanout.worker --consumer local-evictor` | Requires `DATABASE_URL`. |
| Seed demo data | `uv run python ops/seed/seed.py` | Requires a clean database and a running gateway. |
| Run all tests | `uv run pytest` | Integration tests clear database rows. Stop services first. |
| Run unit tests only | `env -u DATABASE_URL uv run pytest tests/unit` | No database needed. |
| Start console (fixtures) | `cd console && npm run dev` | No backend required. |
| Start console (live) | `VITE_FORENSICS_URL=http://localhost:8002 VITE_QUARANTINE_URL=http://localhost:8001 npm run dev` | Run from `console/`. Requires running services. |
| Build console | `cd console && npm ci && npm run build` | Output goes to `console/dist/`. Not committed. |
| Run fleet demo | `uv run python -m fleet.run --ticks 4` | Requires clean database, running gateway, and exported environment. |
| Inspect fleet working memory | `uv run python -m fleet.show --agent ops` | Run after the fleet demo. |
| Configure AOST retention | `bash ops/chaos/configure-gc.sh` | Local cluster only. Sets 24-hour garbage collection window for time-travel queries. |

---

## Service and API reference

The `/docs` page on each running service is the authoritative schema reference.
The most commonly used endpoints are listed below.

### Attest gateway (port 8000)

| Endpoint | What it does |
| --- | --- |
| `POST /agents` | Register a new agent. Returns an `agent_id`. |
| `POST /sources` | Register an input source with a trust tier. Returns a `source_id`. |
| `POST /beliefs` | Write an attested belief. Accepts optional `source_id`, `parent_ids`, and a 1024-float `embedding`. |
| `GET /agents/{agent_id}/chain/verify` | Verify the agent's complete signed hash chain. |
| `GET /healthz` | Returns `{"status":"ok"}` if the service can reach the database. |

### Quarantine service (port 8001)

| Endpoint | What it does |
| --- | --- |
| `POST /taint/preview` | Read-only. Returns the full contamination closure without changing any data. |
| `POST /recant` | Opens an incident and quarantines the full closure in one serializable transaction. |
| `GET /healthz` | Returns `{"status":"ok"}`. |

### Forensics API (port 8002)

| Endpoint | What it does |
| --- | --- |
| `GET /board` | Live agents, sources, beliefs, and the derivation graph. |
| `GET /beliefs/{belief_id}/provenance` | Source, parent and child edges, and verification state for one belief. |
| `GET /agents/{agent_id}/beliefs?as_of=<ISO-8601>` | CockroachDB AS OF SYSTEM TIME time-travel view. |
| `GET /agents/{agent_id}/custody-chain` | Full verified custody chain for an agent. |
| `GET /incidents/{incident_id}` | Incident summary and signed actions. |
| `GET /incidents/{incident_id}/affidavit` | Template or Bedrock-generated incident affidavit. |
| `GET /healthz` | Returns `{"status":"ok"}`. |

---

## Integrating an agent

Write all beliefs through the gateway rather than directly to the database.
`recant_client.py` is a small HTTP client with no framework dependency beyond
`httpx`:

```python
from recant_client import RecantClient

with RecantClient() as recant:
    agent_id = recant.register_agent("support-bot", region="us-east")
    trusted = recant.register_source(
        "https://vendor.example/refund-policy", "verified"
    )
    unsafe = recant.register_source(
        "https://forum.example/thread/42", "untrusted"
    )

    recant.remember(agent_id, "Refunds are available for 30 days.", source_id=trusted)
    bad_belief = recant.remember(
        agent_id, "Refunds can be extended to a year.", source_id=unsafe
    )
    recant.remember(
        agent_id,
        "Approve a 365-day refund.",
        parent_ids=[bad_belief],
    )

    preview = recant.preview(unsafe)       # read-only, no mutation
    incident = recant.recant(unsafe)       # quarantines the full closure
    proof = recant.incident(incident["incident_id"])
```

The client accepts alternate service base URLs as constructor arguments.
Supplying your own embedding requires exactly 1024 floats. If you do not supply
one, the configured embedder generates one. In production, replace the
deterministic development signer before setting `RECANT_ENV=production`: the
development signer will refuse to issue signatures in that mode.

---

## Optional features

### Fleet eviction demonstration

This shows the full end-to-end flow: agents write beliefs, a source is recanted,
the eviction worker runs, and the contaminated beliefs disappear from agent
working memory.

Start with a clean local database, and make sure the services launcher and the
eviction worker are already running. Then:

```bash
set -a
. ./.env
set +a
uv run python -m fleet.run --ticks 4
uv run python -m fleet.show --agent ops
```

Now recant the untrusted source using the commands from Step 9. Wait a moment
for the fanout worker to process the event, then run `fleet.show` again:

```bash
uv run python -m fleet.show --agent ops
```

The contaminated working-memory entries will be gone and the pending refund
action will be marked aborted.

The fleet runner will fail rather than duplicate data if custody records already
exist. Reset the local cluster first if you want a fresh replay.

### Scale test

`ops/scale_test.py` stress-tests the taint engine and recant path with a large
number of agents and beliefs. It deletes all rows before creating its workload.
Its own guard allows only `localhost` or `127.0.0.1` as the target URL.

```bash
set -a
. ./.env
set +a
SCALE_AGENTS=40 SCALE_TAINTED=800 SCALE_NOISE=1200 \
  uv run python ops/scale_test.py
```

### AWS integrations

The default local configuration uses deterministic hash embeddings and a
hard-coded affidavit template. Optional cloud features are:

| Setting | What it enables | Requirements |
| --- | --- | --- |
| `RECANT_EMBEDDER=titan` | Amazon Titan Text Embeddings V2 for semantic vector matching | AWS credentials and Bedrock access with a 1024-dimensional model |
| `RECANT_AFFIDAVIT=bedrock` | Claude-generated incident affidavit | AWS credentials and Bedrock model access. Falls back to the template on any runtime failure. |
| `RECANT_EVIDENCE_BUCKET=<bucket>` | `POST /incidents/{id}/archive` endpoint | AWS credentials and write access to the named S3 bucket |
| `fanout/iac/package.sh` and `deploy.sh` | Package and deploy the Lambda/EventBridge fanout path | AWS CLI, a cloud database URL in `.env`, and a CockroachDB Cloud CA certificate |

Keep all AWS credentials and the `DATABASE_URL_CLOUD` value in the `.env` file.
Never commit them to source control.

Additional documentation:

- `docs/mcp-setup.md` covers CockroachDB Cloud MCP configuration.
- `docs/demo-script.md` describes the presentation flow for the console.
- `docs/plan.md` records implementation decisions and historical status.

---

## Troubleshooting

### Docker is not reachable

**Symptom:** `failed to connect to the docker API` or `Cannot connect to the
Docker daemon`.

**Resolution:** Start Docker Desktop. If you are on WSL 2, open Docker Desktop,
go to Settings, then Resources, then WSL integration, and enable it for your
distribution. Confirm access with `docker info`, then rerun `bash ops/chaos/init.sh`.

### The cluster does not become ready

**Symptom:** `bash ops/chaos/init.sh` hangs or the health check times out.

**Resolution:** Check logs with:

```bash
docker compose -f ops/chaos/docker-compose.yml logs roach1
```

Confirm that ports 26257 and 8080 are not already in use:

```bash
lsof -nP -iTCP:26257 -sTCP:LISTEN
lsof -nP -iTCP:8080   -sTCP:LISTEN
```

If another process holds them, stop it, then rerun the init script.

### DATABASE_URL is not set

**Symptom:** `DATABASE_URL: not set and no .env found`.

**Resolution:** Export the variables in the current shell:

```bash
set -a
. ./.env
set +a
```

Only `ops/run-services.sh` loads `.env` automatically. Every other command
needs the variables exported manually.

### Migration fails

**Symptom:** `uv run python -m db.migrate` reports a connection error.

**Resolution:** The database container must be running before migrations are
applied. Check with:

```bash
docker compose -f ops/chaos/docker-compose.yml ps
```

If the containers are not running, start them first with `bash ops/chaos/init.sh`.
Migrations are tracked and safe to repeat.

### Service ports are already in use

**Symptom:** `ports 8000/8001/8002 are already in use`.

**Resolution:** Identify the process:

```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN
```

Repeat for ports 8001 and 8002. Stop that specific process, then restart the
launcher. If the process is a previous service launch, you can stop all three
at once:

```bash
pkill -f 'uvicorn services'
```

### Seeder says the database is already seeded

**Symptom:** The seeder exits with an error saying data already exists.

**Resolution:** This is expected behavior. The seeder refuses to duplicate data.
If you want to start the demo from scratch, reset the local cluster (this
destroys all local data):

```bash
bash ops/chaos/reset.sh
bash ops/chaos/init.sh
uv run python -m db.migrate
uv run python ops/seed/seed.py
```

### Integration tests fail with concurrency errors

**Symptom:** Tests fail with `40001`, `WriteTooOld`, or `unknown agent` errors.

**Resolution:** Stop all running services and the fanout worker, then reset:

```bash
bash ops/chaos/reset.sh
```

The local unlicensed multi-node CockroachDB cluster can throttle concurrency
after its grace period. Resetting the cluster resolves this. The reset is
destructive and removes all local data.

### A recant quarantines beliefs but working memory does not change

**Symptom:** Belief statuses in the database say quarantined, but agent working
memory still holds the old values.

**Resolution:** The fanout worker must be running to process eviction events.
Start it in a separate terminal:

```bash
set -a
. ./.env
set +a
uv run python -m fanout.worker --consumer local-evictor
```

To process events that already exist and then exit:

```bash
uv run python -m fanout.worker --consumer local-evictor --once
```

### The console still shows fixture data after connecting to local services

**Symptom:** You passed `VITE_FORENSICS_URL` and `VITE_QUARANTINE_URL` but the
console still shows the built-in demo data.

**Resolution:** These are build-time Vite variables. You must stop Vite and
restart it with the variables set. Also confirm:

1. Both services return `{"status":"ok"}` from their `/healthz` endpoints.
2. `RECANT_CORS_ORIGINS` in your `.env` includes the exact browser origin
   (for example `http://localhost:5173`). Restart the services after changing
   this value.

### The browser reports a CORS error

**Symptom:** The browser console shows a CORS policy error when the console
makes a request to a local service.

**Resolution:** Open `.env` and set:

```
RECANT_CORS_ORIGINS=http://localhost:5173
```

If you access the console from a different host or port, add that origin to
the comma-separated list. Restart `ops/run-services.sh` after changing the
value.

### npm install or build fails

**Symptom:** `npm ci` or `npm run build` exits with an error.

**Resolution:** Check your Node.js version:

```bash
node --version
```

Node.js 20 or newer is required. If the version is correct, try removing the
installed packages and reinstalling:

```bash
cd console
rm -rf node_modules
npm ci
```

Do not commit the `node_modules` directory or the `console/dist` build output.

### Bedrock, S3, or cloud fanout calls fail

**Symptom:** A service returns a 500 error referencing Bedrock, S3, or Lambda.

**Resolution:** These are optional cloud features. For a fully local run, keep
the following settings in your `.env`:

```
RECANT_EMBEDDER=hash
```

Leave `RECANT_AFFIDAVIT` unset (defaults to the template). Cloud features
require AWS credentials, a configured region, and feature-specific access
(Bedrock model access, S3 bucket permissions, etc.).

### RECANT_ENV=production causes signer errors

**Symptom:** The services refuse to start or return signer errors after setting
`RECANT_ENV=production`.

**Resolution:** This behavior is intentional. The deterministic development
signer is blocked in production mode to prevent it from being used in a real
deployment. Configure a production signer before enabling that setting.

---

## Safety notes

- `ops/chaos/reset.sh` destroys the local CockroachDB Docker volumes and all
  data inside them. Only run it against a local cluster you do not mind losing.
- Integration tests and `ops/scale_test.py` delete local database rows before
  running. Do not point them at any database containing data you want to keep.
- The local cluster is insecure by design, but all ports bind only to
  `127.0.0.1` (loopback). Do not expose these ports externally.
- Keep cloud credentials, `DATABASE_URL_CLOUD`, and any production values in
  the `.env` file, which is listed in `.gitignore`. Never commit them.
- The local outbox worker is the active eviction transport. The cloud
  changefeed and Lambda path are optional deployment infrastructure, not
  required for local development.

---

## License

See [LICENSE](LICENSE).
