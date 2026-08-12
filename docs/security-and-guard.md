# Security and Recant Guard

This document describes the production security model implemented in Recant.
Local development stays zero-configuration, but production fails closed for
identity, tenant isolation, provenance, and signing.

## Security guarantees

Recant provides these enforceable properties:

- Every belief is appended through a serializable per-agent write and signed.
- New v2 belief attestations bind the tenant, content, parents, source,
  retrieval receipt, least authority, all source origins, and provenance method.
- Derived beliefs inherit the minimum authority and the union of source origins
  from all parents. Authority cannot increase through summarization.
- A source recant quarantines explicit descendants and evidence-backed semantic
  copies, revokes unused action permits, and emits one durable outbox event in
  the same transaction.
- New v2 quarantine attestations bind the tenant, source, incident, actor, and
  exact set of newly flipped beliefs.
- Guard decisions are immutable signed records. Permits are short-lived,
  exact-argument, policy-version-bound, and single-use.
- CockroachDB row-level security is a backstop for every tenant transaction.
- Merkle checkpoints can publish signed chain heads to an independent S3
  bucket, making later chain rollback detectable.

## Production defaults

Setting `RECANT_ENV=production` enforces:

| Control | Production behavior |
| --- | --- |
| `RECANT_AUTH_MODE` | Required bearer authentication |
| `RECANT_DB_RLS` | Every tenant transaction executes under its tenant SQL role |
| `RECANT_REQUIRE_PROVENANCE` | New beliefs require a source or signed context receipt |
| Agent signing | `kms_key_arn` is required for every registered agent |
| Control signing | `RECANT_CONTROL_KMS_KEY_ARN` is required |
| Idempotency replay | `RECANT_IDEMPOTENCY_ENCRYPTION_KEY` protects stored responses |
| Checkpoints | `RECANT_CHECKPOINT_BUCKET` is required when creating a checkpoint |
| Guard effects | Sensitive actions require a signed context receipt |
| Confirmation | The confirmer must be a different API principal |

Explicit false values cannot disable authentication, RLS, or provenance in
production. Development retains opt-in flags for local testing.

## Identity and roles

API tokens are random bearer secrets. CockroachDB stores only a SHA-256 digest.
The first token is printed once by `ops/provision_tenant.py` and should move
directly into a secret manager.

| Role | Capability |
| --- | --- |
| `writer` | Register agents, write beliefs, create receipts, request decisions, consume permits |
| `source_admin` | Register `partner` and `verified` sources and their authority assertions |
| `operator` | Execute recants, confirm actions, create checkpoints, verify claim relations |
| `auditor` | Read boards, custody records, incidents, decisions, and checkpoints |
| `policy_admin` | Register tool policy and verify claim relations |

An endpoint accepts only the smallest applicable role set. In production, the
principal that requests an action cannot confirm the same action.

## Tenant isolation and provisioning

Run migrations with a database administrator. Then provision a tenant:

```bash
DATABASE_URL='postgresql://admin:...@cluster:26257/recant?sslmode=verify-full' \
uv run python ops/provision_tenant.py acme \
  --display-name 'Acme' \
  --subject owner \
  --roles writer,source_admin,operator,auditor,policy_admin \
  --app-db-role recant_app
```

The script creates:

1. One tenant row.
2. One API principal and a hash-only token record.
3. A SQL role named from the tenant UUID.
4. Table grants for that tenant role.
5. Membership from the shared application database role to the tenant role.

The application authenticates while using the shared role, then executes
`SET LOCAL ROLE` inside the transaction. RLS policies compare `current_user()`
with the role derived from the authenticated tenant UUID. A query that omits a
tenant predicate still cannot see another tenant's rows.

Run one local fanout worker per tenant when RLS is enabled and set
`RECANT_TENANT_ID`. The AWS consumer derives the role from each signed-in outbox
event automatically.

## KMS signing

Use asymmetric AWS KMS keys with:

- Key usage: `SIGN_VERIFY`
- Key spec: an ECC NIST P-256 signing key
- Signing algorithm: `ECDSA_SHA_256`

Register each agent with its own `kms_key_arn`. Set
`RECANT_CONTROL_KMS_KEY_ARN` to a separate control-plane key used for source
authority assertions, quarantine actions, Guard receipts and decisions,
permits, and custody checkpoints.

Recant sends a 32-byte SHA-256 digest to KMS with `MessageType=DIGEST`. Each
record stores the signing algorithm, key identifier, and DER public key needed
for offline verification. Deterministic Ed25519 keys remain available only for
local development and refuse to sign in production.

The application role needs `kms:GetPublicKey` and `kms:Sign` only for the
configured keys. Do not grant KMS key administration to the runtime role.

## Authority model

Trust tiers map to monotonic numeric authority:

| Source or evidence | Rank |
| --- | ---: |
| Unknown or unattributed | 0 |
| Untrusted external source | 10 |
| Public source | 20 |
| Authoritative tool result | 30 |
| Partner source | 40 |
| User history | 50 |
| Verified source | 60 |
| Independent user confirmation | 70 |
| Internal system assertion | 90 |

The current source registration API exposes the four source tiers from 10 to
60. Higher ranks are reserved for policy and confirmation. A child belief gets
the minimum rank of every direct source and parent, and it keeps the union of
all origin source IDs. This is the non-amplification rule.

## Guard request flow

### 1. Sign retrieved context

Call `POST /contexts/receipts` with the exact active belief IDs retrieved for
the agent. The signed receipt binds each belief hash, all origins, the minimum
authority, the requesting principal, and a short expiry.

When a derived belief includes `context_receipt_id`, the gateway verifies the
receipt and records every receipt belief as an explicit parent. The new v2
belief chain signs that receipt and propagated provenance.

### 2. Authorize an action

Call `POST /actions/authorize` with the agent, tool name, exact JSON arguments,
support belief IDs, and receipt ID. The decision compares observed authority
with a stored or built-in policy.

Built-in defaults are conservative:

| Tool suffix | Risk | Required authority | Confirmation |
| --- | --- | ---: | --- |
| `read`, `search`, `lookup` | read | 10 | no |
| `navigate` | navigate | 50 | yes |
| `refund`, `send_email` | effect | 70 | yes |
| `purchase` | purchase | 70 | yes |
| `credential` | credential | 70 | yes |
| unknown tool | effect | 70 | yes |

MCP-style annotations can raise a policy to destructive effect risk. They
cannot lower a stored or built-in risk class because tool annotations are not
treated as an authority boundary.

### 3. Confirm when required

A `confirm` result has no permit. A principal with the `operator` role calls
`POST /actions/decisions/{id}/confirm`. Production rejects self-confirmation.
The confirmation creates a signed superseding `allow` decision with rank 70.

### 4. Consume at the executor boundary

Immediately before the external tool call, send the permit, tool name, and
arguments to `POST /actions/permits/consume`. Guard verifies:

- Stored token hash and signature
- Tenant, agent, decision, nonce, policy version, and expiry
- Exact tool and canonical argument digest
- Single-use and revocation state
- Current active status of every support belief
- The configured control signer and the exact canonical permit bytes

Before authority is evaluated, Guard also reconstructs each support belief's
signed v1 or v2 payload, verifies its chain hash and configured agent signer,
and treats legacy v1 authority as zero because v1 did not sign that field.
Receipts are checked again against current belief hashes, origins, authority,
and status. Confirmation verifies the original signed decision before issuing
a superseding permit.

Only a successful atomic consume authorizes execution. A recant revokes unused
permits synchronously. The fanout worker also aborts pending action records.

## Semantic evidence

Vector similarity alone can expand taint only into an unattributed belief. A
source-backed belief needs stored `equivalent` or `entails` evidence, or exact
normalized content, before it can join another source's closure. This prevents
a topically similar but contradictory policy, such as 30 days versus 365 days,
from being quarantined merely because its embedding is close.

`RECANT_CLAIM_VERIFIER=conservative` is offline and accepts only exact content
plus high-precision numeric contradictions. `bedrock` stores model ID, method,
version, confidence, and relation. Equivalence or entailment below 0.85 is
downgraded to unknown and cannot expand closure.

## Idempotency

Agent, source, belief, receipt, recant, authorization, and confirmation writes
accept `Idempotency-Key`. The key is atomically claimed inside the same
transaction and scoped by tenant, principal, method, and path for 24 hours.
Concurrent retries cannot perform the mutation twice. Reusing an unexpired key
with the same canonical request replays the original response; different input
returns HTTP 409. An expired key can be reclaimed. `RecantClient` creates a
fresh key automatically unless the caller provides a stable workflow key.
Replay responses are encrypted with AES-256-GCM and authenticated against the
tenant, principal, request path, idempotency key, and request digest. This keeps
one-use permit tokens out of plaintext database rows. Production requires a
secret 32-byte base64 or 64-character hex
`RECANT_IDEMPOTENCY_ENCRYPTION_KEY`; generate a base64 value with
`openssl rand -base64 32` and keep it in the runtime secret manager.

## Tenant-scoped vector search

The cosine vector index uses `(tenant_id, embedding vector_cosine_ops)`, and
every approximate nearest-neighbor query constrains the tenant prefix before
`ORDER BY ... LIMIT`. This avoids both cross-tenant candidates and false
negatives caused by another tenant crowding the global top-K set.

Primary reference: [CockroachDB vector indexes and prefix columns](https://www.cockroachlabs.com/docs/stable/vector-indexes).

## Custody checkpoints

`POST /checkpoints` creates sorted leaves from every agent's committed chain
head, computes a deterministic Merkle root, links the previous root, and signs
the checkpoint. `GET /checkpoints/{id}/verify` separately reports:

- Signature validity
- Stored Merkle root validity
- Whether current chain heads still match
- Whether an optional external S3 copy matches

Set `RECANT_CHECKPOINT_BUCKET` to publish an encrypted independent copy. If
`RECANT_OBJECT_LOCK_DAYS` is greater than zero, the bucket must already have S3
Object Lock enabled. Use a retention mode that matches your legal and recovery
requirements. A publication failure returns HTTP 502 and leaves the signed
local checkpoint available for diagnosis.

## Fanout security and durability

The cloud deployment creates an encrypted, versioned manifest bucket for
events too large for EventBridge. The consumer pins the bucket and object key,
limits manifest size, verifies SHA-256, and then requires an exact match with
the tenant's append-only CockroachDB outbox row before any eviction.

The Lambda Function URL uses AWS `NONE` edge auth because CockroachDB does not
SigV4-sign webhook requests. The receiver still requires a stable Basic header
whose secret is stored in SSM; Lambda receives only its SHA-256 digest.
The deployment grants both `lambda:InvokeFunctionUrl` and the newer required
`lambda:InvokeFunction`, with the latter restricted to Function URL requests.
CockroachDB supports this through `webhook_auth_header`. EventBridge retries for
up to 24 hours and routes exhausted deliveries to an SQS dead-letter queue.

Relevant primary documentation:

- [CockroachDB webhook changefeed authentication](https://www.cockroachlabs.com/docs/stable/create-changefeed)
- [AWS EventBridge dead-letter queues](https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-rule-dlq.html)
- [AWS Lambda webhook authentication guidance](https://docs.aws.amazon.com/lambda/latest/dg/urls-webhook-tutorial.html)
- [AWS Lambda Function URL access control](https://docs.aws.amazon.com/lambda/latest/dg/urls-auth.html)

## Boundaries and operational limits

- Recant proves custody and policy evaluation. It does not prove that a source
  statement was true when first ingested.
- A writer chooses which beliefs enter a context receipt. Integrate receipt
  creation at the trusted retrieval boundary so the set is complete.
- Conservative semantic verification favors false negatives over unsafe false
  positives. Review unknown relations or enable the Bedrock verifier.
- Permit consumption and an external provider call are not one distributed
  transaction. Use the action digest as the downstream idempotency key when the
  provider supports it. If a call fails after consumption, reauthorize.
- Recant cannot reverse an external effect already executed. It prevents future
  use, revokes pending capabilities, and preserves the evidence needed for
  compensation.
- The demo fleet's LangChain working-memory rows carry tenant metadata and are
  protected by RLS. A different production vector store must provide an
  equivalent tenant-aware read, write, and eviction boundary.
- A database administrator remains powerful. Keep KMS administration separate,
  publish checkpoints outside the database, monitor checkpoint failures, and
  restrict direct table writes.

## Deployment checklist

1. Use a TLS-verified CockroachDB URL and a non-admin application role.
2. Apply migrations, then provision each tenant and store the token once.
3. Set `RECANT_ENV=production` and do not disable auth, RLS, or provenance.
4. Configure separate agent and control-plane KMS keys with least privilege.
5. Configure a 32-byte idempotency-response encryption key.
6. Configure CORS with exact console origins, never `*` for a credentialed UI.
7. Put API tokens, database URLs, and AWS credentials in a secret manager.
8. Configure the checkpoint bucket, Object Lock if required, fanout DLQ alarms,
   and changefeed lag monitoring.
9. Run CI, dependency audits, integration tests, and a checkpoint verification
   before each release.
