# Demo Video Script

Recorded in the console's Recording Mode (see `recant-frontend` skill). Hard limit: **2:55**.

| Time | Beat | What is on screen | Proof moment |
|------|------|--------------------|--------------|
| 0:00-0:20 | Problem | Memory poisoning is the new prompt injection; agents share and paraphrase memory. | - |
| 0:20-0:45 | Poisoned ingest | Three agents working; a poisoned web source injects "refund window is 365 days"; the custody chain shows it entering. | 1. Attested write |
| 0:45-1:05 | Paraphrase spreads | Agent B paraphrases agent A's poisoned fact into its own memory; no explicit FK link exists between the two beliefs. | 2. Semantic derivation |
| 1:05-1:40 | Quarantine | `recant(source)` runs one serializable transaction that quarantines the original and the paraphrase (vector taint); judge overlay flashes SERIALIZABLE TXN and VECTOR kNN with latency; the ops agent's pending refund aborts via changefeed. | 3. `recant()`, 4. Changefeed eviction |
| 1:40-2:10 | AOST replay | Split-screen: agent B's belief set at a past timestamp vs now; Bedrock prints the incident affidavit. | 5. AOST replay |
| 2:10-2:35 | Node kill | A node is killed mid-forensics-query; the answer still returns; the MCP audit log is shown on screen. | 6. Node kill |
| 2:35-2:55 | Recap card | Tools recap: 4 CockroachDB tools, 4 AWS services, repo link + live demo URL. | - |
