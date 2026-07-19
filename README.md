# Recant

Recant is a provenance and retraction substrate for shared agent memory. It
records who wrote each belief, where it came from, and its signed hash-chain
position. When a source is found to be unsafe, `recant(source_id)` quarantines
the full contamination closure: direct citations, explicit descendants, and
semantically similar copies that have no recorded edge. A durable outbox then
evicts those beliefs from agent working memory and aborts pending actions based
on them.

It is not a chatbot or a RAG application. It is the custody and incident
response layer beneath an agent-memory system.

The deployed console is a deterministic fixture demo: [recant.vercel.app](https://recant.vercel.app).
It does not need a backend. The repository also contains the complete local
CockroachDB, FastAPI, fleet, and fanout workflow described below.

## What is in the repository

| Component | Location | Responsibility |
| --- | --- | --- |
| Attest gateway | `services/attest_gateway/` | Only supported write path. Creates agents and sources, attests beliefs, and maintains each agent's signed hash chain. |
| Quarantine service | `services/quarantine/` | Previews and executes `recant(source_id)` in a serializable transaction. |
| Forensics API | `services/forensics/` | Read-only board, provenance, custody-chain, incident, evidence, and time-travel queries. |
| Taint engine | `services/taint_engine/` | Traverses explicit derivations and vector similarity matches. |
| Fanout | `fanout/` | Local durable outbox worker and AWS Lambda/EventBridge implementation for eviction. |
| Demo fleet | `fleet/` | Three deterministic agents with CockroachDB-backed working memory. |
| Web console | `console/` | Vite/React UI. It uses fixtures unless live API URLs are configured. |
| Database | `db/migrations/` | Ordered CockroachDB schema migrations. |

## Prerequisites

For the full local stack, install:

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) or Docker Engine with the Compose plugin. It runs the local three-node CockroachDB cluster.
- [uv](https://docs.astral.sh/uv/), which provisions the project Python version and dependencies. You do not need a separate Python installation.
- Node.js 20+ and npm, only for the console.
- Git.

On macOS, one possible installation is:

```bash
brew install --cask docker
brew install uv node git
```

On Windows, install Docker Desktop, uv, Node.js, and Git, then run the shell
commands in **WSL2**. The operational scripts are Bash scripts. Enable Docker
Desktop's WSL integration and confirm `docker info` works in that WSL terminal
before continuing.

The database URLs in this README use the local, insecure, loopback-only
development cluster. Do not reuse them for a remote or production database.

## Fastest path: run only the console

This is the quickest way to view the product. It uses deterministic fixture
data and requires neither Docker nor Python services.

```bash
git clone https://github.com/thamothara7/recant.git
cd recant/console
npm ci
npm run dev
```

Open <http://localhost:5173>. Press `Ctrl+C` to stop Vite.

## Full local setup

These steps create a disposable local cluster, install dependencies, apply the
schema, test it, run the services, and seed the deterministic incident story.
All commands below are run from the repository root unless a command changes
directory explicitly.

### 1. Clone and create local configuration

```bash
git clone https://github.com/thamothara7/recant.git
cd recant
cp .env.example .env
uv sync
```

`.env` is ignored by Git. The example defaults are safe for the local Docker
cluster. To make them available to one shell, run:

```bash
set -a
. ./.env
set +a
```

`ops/run-services.sh` loads `.env` itself. Commands such as migrations, tests,
the worker, and the fleet need the variables exported as above.

### 2. Start CockroachDB and apply migrations

Start Docker Desktop or Docker Engine first, then verify that the current shell
can reach it:

```bash
docker info
bash ops/chaos/init.sh
uv run python -m db.migrate
docker compose -f ops/chaos/docker-compose.yml ps
```

The command prints this local connection string when the cluster is ready:

```text
postgresql://root@localhost:26257/recant?sslmode=disable
```

The CockroachDB admin UI is available at <http://localhost:8080>. The database
ports are deliberately bound to loopback addresses only.

### 3. Run tests before seeding

```bash
uv run pytest
cd console && npm ci && npm run build && cd ..
```

`pytest` runs unit and integration tests when `DATABASE_URL` is exported. The
integration fixtures delete rows before every test, so stop local services and
do not point this command at a database containing data you want to keep.

To run only the database-free unit suite:

```bash
env -u DATABASE_URL uv run pytest tests/unit
```

### 4. Run the services and the local eviction worker

Open two terminals at the repository root.

Terminal 1 starts the HTTP services and reads `.env` automatically:

```bash
bash ops/run-services.sh
```

| Service | URL | Interactive API documentation |
| --- | --- | --- |
| Attest gateway | <http://localhost:8000> | <http://localhost:8000/docs> |
| Quarantine service | <http://localhost:8001> | <http://localhost:8001/docs> |
| Forensics API | <http://localhost:8002> | <http://localhost:8002/docs> |

Terminal 2 runs the durable local outbox consumer. It is required to observe
working-memory eviction and action abortion after a recant:

```bash
set -a
. ./.env
set +a
uv run python -m fanout.worker --consumer local-evictor
```

Verify the stack from a third terminal:

```bash
curl -fsS http://localhost:8000/healthz
curl -fsS http://localhost:8001/healthz
curl -fsS http://localhost:8002/healthz
```

Each should return `{"status":"ok"}`.

### 5. Seed and exercise the incident flow

With the gateway running, seed the fixed contamination scenario:

```bash
set -a
. ./.env
set +a
uv run python ops/seed/seed.py
```

Expected output is `seeded 3 agents, 4 sources, 9 beliefs`. The seed command
intentionally fails if data already exists; this preserves a deterministic
demo rather than silently upserting a second copy.

Preview and then recant the untrusted source:

```bash
source_id="$(curl -fsS http://localhost:8002/board | uv run python -c '
import json, sys
print(next(s["source_id"] for s in json.load(sys.stdin)["sources"] if s["trust_tier"] == "untrusted"))
')"

curl -fsS -X POST http://localhost:8001/taint/preview \
  -H 'content-type: application/json' \
  -d "{\"source_id\":\"$source_id\"}" | uv run python -m json.tool

curl -fsS -X POST http://localhost:8001/recant \
  -H 'content-type: application/json' \
  -d "{\"source_id\":\"$source_id\",\"actor\":\"local-operator\"}" | uv run python -m json.tool
```

The receipt lists the incident ID, every belief in the closure, and the newly
quarantined beliefs. The running worker consumes the resulting `memory_events`
row. Inspect the live graph with:

```bash
curl -fsS http://localhost:8002/board | uv run python -m json.tool
```

### 6. Connect the console to the local services

The console defaults to fixtures. Give Vite both URLs to enable live Explore
mode and live recant requests:

```bash
cd console
npm ci
VITE_FORENSICS_URL=http://localhost:8002 \
VITE_QUARANTINE_URL=http://localhost:8001 \
  npm run dev
```

Open <http://localhost:5173>. These are build-time Vite variables: stop and
restart `npm run dev` after changing them. The frontend must be served from an
origin listed in `RECANT_CORS_ORIGINS` (the local default is
`http://localhost:5173`).

## Everyday commands

| Goal | Command | Notes |
| --- | --- | --- |
| Start database | `bash ops/chaos/init.sh` | Idempotent; needs Docker. |
| Apply schema | `uv run python -m db.migrate` | Requires exported `DATABASE_URL`. |
| Start APIs | `bash ops/run-services.sh` | Gateway `:8000`, quarantine `:8001`, forensics `:8002`. |
| Run local fanout | `uv run python -m fanout.worker --consumer local-evictor` | Uses a durable delivery ledger. Add `--once` to drain and exit. |
| Seed basic story | `uv run python ops/seed/seed.py` | Requires a clean database and gateway. |
| Run agent-memory demo | `uv run python -m fleet.run --ticks 4` | Requires a clean database, gateway, and exported environment. |
| Inspect fleet working memory | `uv run python -m fleet.show --agent ops` | Run after the fleet demo. |
| Run all tests | `uv run pytest` | Integration tests clear database rows. |
| Run console | `cd console && npm run dev` | Fixtures unless `VITE_*` URLs are set. |
| Build console | `cd console && npm ci && npm run build` | Produces ignored `console/dist/`. |
| Configure 24-hour local AOST retention | `bash ops/chaos/configure-gc.sh` | Local cluster only. |

## API map

The FastAPI `/docs` pages are the source of truth for request and response
schemas. The most-used endpoints are:

| Service | Endpoint | Purpose |
| --- | --- | --- |
| Gateway | `POST /agents`, `POST /sources` | Register custody principals and input sources. |
| Gateway | `POST /beliefs` | Attested belief write. Optional `source_id`, `parent_ids`, and 1024-float `embedding`. |
| Gateway | `GET /agents/{agent_id}/chain/verify` | Verify a complete agent hash/signature chain. |
| Quarantine | `POST /taint/preview` | Read-only contamination closure preview. |
| Quarantine | `POST /recant` | Open an incident and quarantine the closure. |
| Forensics | `GET /board` | Live agents, sources, beliefs, and derivation graph. |
| Forensics | `GET /beliefs/{belief_id}/provenance` | Source, parent/child edges, and verification state. |
| Forensics | `GET /agents/{agent_id}/beliefs?as_of=<ISO-8601>` | CockroachDB time-travel view. |
| Forensics | `GET /agents/{agent_id}/custody-chain` | Full verified custody chain. |
| Forensics | `GET /incidents/{incident_id}` | Incident summary and signed actions. |
| Forensics | `GET /incidents/{incident_id}/affidavit` | Template or Bedrock-generated incident affidavit. |

Every service exposes `GET /healthz`. Use it before debugging an application
request; it tests the application-to-database connection.

## Integrating an agent

Use the gateway for every memory write rather than writing straight to the
vector table. `recant_client.py` is a small HTTP client with no framework
dependency beyond `httpx`:

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

    preview = recant.preview(unsafe)       # no mutation
    incident = recant.recant(unsafe)       # quarantines full closure
    proof = recant.incident(incident["incident_id"])
```

The client accepts alternate service base URLs in its constructor. Supplying
your own embedding requires exactly 1024 floats; otherwise the configured
embedder generates one. In production, replace the deterministic development
signer before setting `RECANT_ENV=production`: the development signer refuses
to issue signatures in that mode.

## Tests and a practical bug-fixing workflow

There is no configured lint or formatter command. The repeatable quality gates
are the Python test suite and the TypeScript/Vite production build.

1. Reproduce the issue with the smallest test or API request possible.
2. Add or update a focused test under `tests/unit/` when no database is
   needed; use `tests/integration/` for CockroachDB behavior.
3. Run the focused test, then the appropriate full suite:

   ```bash
   uv run pytest tests/unit
   uv run pytest tests/integration
   cd console && npm run build
   ```

4. For a behavior that crosses a service boundary, use the deterministic seed,
   call `/taint/preview` before `/recant`, and inspect `/board` plus the worker
   output afterward.
5. Before committing, check that generated local files were not staged:

   ```bash
   git status --short
   git diff --check
   ```

The integration suite owns its database state: it calls migrations and deletes
rows before each test. Stop `ops/run-services.sh`, the fanout worker, and the
fleet before running it. Never point it at a cloud or shared environment.

## Troubleshooting

| Symptom | Cause and resolution |
| --- | --- |
| `failed to connect to the docker API` | Docker Desktop/Engine is stopped or WSL cannot access it. Start Docker Desktop, enable WSL integration if applicable, run `docker info`, then rerun `bash ops/chaos/init.sh`. |
| Cluster does not become ready | Inspect `docker compose -f ops/chaos/docker-compose.yml logs roach1`. Confirm ports 26257 and 8080 are free, then rerun the init script. |
| `DATABASE_URL` is missing | Run `set -a; . ./.env; set +a` in the current shell. Only `ops/run-services.sh` loads `.env` automatically. |
| Migration fails because the database is unreachable | Start the cluster first. Confirm with `docker compose -f ops/chaos/docker-compose.yml ps`, then re-run `uv run python -m db.migrate`; migrations are tracked and safe to repeat. |
| Service launcher says ports 8000, 8001, or 8002 are busy | Identify the process with `lsof -nP -iTCP:8000 -sTCP:LISTEN` (repeat for the other ports), stop that specific process, and restart the launcher. |
| Seeder says `already seeded` | This is expected on a non-empty demo database. Keep the data and skip seeding, or reset the **local** cluster with `bash ops/chaos/reset.sh`; reset destroys its Docker volumes and data. |
| Integration test fails with `40001`, `WriteTooOld`, or unexpected `unknown agent` errors | Stop APIs/workers, then run `bash ops/chaos/reset.sh`. The local unlicensed multi-node CockroachDB setup can throttle concurrency after its grace period; reset is destructive but restores a clean local cluster. |
| A recant changes belief statuses but working memory/action state does not change | Start `fanout.worker` with the same exported `DATABASE_URL`. To process existing events once, run `uv run python -m fanout.worker --consumer local-evictor --once`. |
| Console still shows fixtures | Set both `VITE_FORENSICS_URL` and `VITE_QUARANTINE_URL`, then restart Vite. Confirm the APIs' `/healthz` endpoints work and that `RECANT_CORS_ORIGINS` exactly includes the browser origin. |
| Browser reports a CORS error | Set `RECANT_CORS_ORIGINS` to a comma-separated list of exact origins, for example `http://localhost:5173,http://127.0.0.1:5173`, and restart the affected API services. |
| `npm ci` or `npm run build` fails | Check `node --version`, remove only `console/node_modules`, then rerun `npm ci`. Do not commit `node_modules` or `console/dist`. |
| Bedrock, S3 archive, or cloud fanout call fails locally | These are optional. Leave `RECANT_EMBEDDER=hash` and the default affidavit template for a fully local run. Cloud features require AWS credentials, a region, Bedrock model access, and their feature-specific configuration. |
| `RECANT_ENV=production` causes signer errors | Expected: the deterministic development signer is intentionally blocked in production mode. Configure a production signer before using that setting. |

## Optional features

### Fleet eviction demonstration

Use a clean local database, with the API launcher and worker already running:

```bash
set -a
. ./.env
set +a
uv run python -m fleet.run --ticks 4
uv run python -m fleet.show --agent ops
```

Recant the untrusted source as shown in the quickstart, wait for the worker,
then rerun `fleet.show`. The contaminated working-memory entries disappear and
the pending refund action is aborted. The fleet runner fails rather than
upserting if custody data already exists; reset the local cluster first when
you want a fresh replay.

### Scale test

`ops/scale_test.py` deletes all rows before creating its workload. Its own
guard only permits a `localhost` or `127.0.0.1` URL; still verify the target
before running it:

```bash
set -a
. ./.env
set +a
SCALE_AGENTS=40 SCALE_TAINTED=800 SCALE_NOISE=1200 \
  uv run python ops/scale_test.py
```

### AWS integrations

The default local mode uses deterministic hash embeddings and a deterministic
affidavit template. Optional cloud settings are:

| Setting | Effect | Requirements |
| --- | --- | --- |
| `RECANT_EMBEDDER=titan` | Amazon Titan Text Embeddings V2 | AWS credentials, Bedrock access, 1024-dimensional model. |
| `RECANT_AFFIDAVIT=bedrock` | Claude-generated incident affidavit | AWS credentials and Bedrock model access. Falls back to a template on runtime failure. |
| `RECANT_EVIDENCE_BUCKET=<bucket>` | Enables `POST /incidents/{id}/archive` | AWS credentials and write access to the named S3 bucket. |
| `fanout/iac/package.sh` / `deploy.sh` | Packages and deploys Lambda/EventBridge fanout | AWS CLI, cloud database URL in local `.env`, and CockroachDB Cloud CA certificate. |

Read [docs/mcp-setup.md](docs/mcp-setup.md) for CockroachDB Cloud MCP notes,
[docs/demo-script.md](docs/demo-script.md) for the presentation flow, and
[docs/plan.md](docs/plan.md) for implementation decisions and historical
status. Keep cloud credentials and `DATABASE_URL_CLOUD` in the ignored `.env`
file, never in source control.

## Safety notes

- `ops/chaos/reset.sh` destroys the local CockroachDB Docker volumes.
- Integration tests and `ops/scale_test.py` delete local database rows.
- The local cluster is insecure by design, but its ports bind only to
  `127.0.0.1`.
- The local outbox worker is the active eviction transport. The cloud
  changefeed/Lambda path is optional deployment infrastructure.

## License

See [LICENSE](LICENSE).
