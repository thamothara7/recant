# Demo Video Script

Record at 1280 by 720 in the console's Recording Mode. Target **2:50** and do
not exceed Devpost's three-minute limit.

## Before recording

1. Open https://recant.vercel.app in a clean browser window.
2. Select **Explore**, turn on **Advanced**, **Judge overlay**, and
   **Recording**, then select the reset button.
3. Open `docs/architecture.svg` in a second tab.
4. Prepare a terminal at the repository root with
   `bash ops/inspect_cloud_cluster.sh` typed but not yet run.
5. Close notifications and rehearse the cuts once. The public console is a
   deterministic replay, so no action depends on live typing or network luck.

## Record on macOS

1. Set the browser content area to 1280 by 720, keep zoom at 100 percent, and
   enter full screen so bookmarks, unrelated tabs, and personal information are
   not captured.
2. Press **Shift-Command-5**, choose **Record Selected Portion**, and frame only
   the browser content. Under **Options**, select the microphone you rehearsed
   with and disable the timer unless you need it.
3. Start recording, wait one second, then follow the timed sequence below. Use
   the Demo Director buttons instead of typing shortcuts so each action is
   visible to judges.
4. Stop from the menu bar. Open the recording in QuickTime Player, choose
   **Edit > Trim**, remove dead air, and keep the final duration at or below
   2:50.
5. Watch the exported file once at normal speed. Confirm that narration is
   audible, the vector and transaction overlays are readable, and no
   notification, credential, private tab, or unrelated brand appears.
6. Upload the file to YouTube or Vimeo as **Public**. Do not add copyrighted
   music. Open the final URL in a signed-out window before adding it to Devpost.

## Timed recording

| Time | Screen action | Narration |
| --- | --- | --- |
| 0:00-0:14 | Show the architecture diagram. | "AI agents copy and paraphrase shared memory. When one source is poisoned, deleting one row is not enough. Recant is the custody and incident-response layer that takes the bad fact back everywhere and proves what happened." |
| 0:14-0:31 | Cut to the Explore board. Point to the three agents and the untrusted-source review chip. | "Here, three agents share operational memory. A forum post says the refund window is 365 days. The support agent stores it, another agent rewords it, and an operations agent prepares to act on it." |
| 0:31-0:49 | Select demo moment **1 Write**. Let the custody thread and `SERIALIZABLE TXN` chip land. | "Every belief enters through one Attest Gateway. CockroachDB stores its tenant, source, authority, parents, database timestamp, signature, and position in a per-agent hash chain. Working memory is only a disposable copy." |
| 0:49-1:07 | Select **2 Derive**. Hold on the dashed inferred edge and `VECTOR kNN` chip. | "This paraphrase has no recorded provenance edge. A tenant-prefixed CockroachDB cosine vector index finds it in the same transactional store. Similarity discovers the candidate, while stored claim evidence and source authority decide whether it can join the contamination closure." |
| 1:07-1:36 | Select **3 Recant**. Do not move the pointer while the sweep, status flip, and overlay chips play. | "One `recant(source_id)` call follows direct citations, explicit descendants, and the vector match. A serializable transaction quarantines the closure, signs the action, revokes unused permits, and appends an eviction event. The three affected memories flip together, including the reworded copy." |
| 1:36-1:54 | Select **4 Evict**. Point to the blocked operations memory and the changefeed activity. | "The outbox stays append-only. An authenticated Lambda receiver validates the CockroachDB event, EventBridge retries delivery, and a consumer evicts agent working memory and aborts dependent actions exactly once through a separate delivery ledger." |
| 1:54-2:10 | Select **5 Replay**. Hold on the past-state banner. | "Forensics can rewind with `AS OF SYSTEM TIME`, rebuild every signed payload from stored fields, and show what each agent believed before containment. Bedrock Claude can turn that verified evidence into an affidavit, with a deterministic fallback." |
| 2:10-2:24 | Select **6 Kill node**. Hold on the cluster status and returned evidence. | "This deterministic beat rehearses the same node-loss path verified against Recant's three-node local cluster before release. CockroachDB remains the source of truth, while Guard still requires a signed decision and a fresh, exact-argument, one-use permit before a consequential tool call." |
| 2:24-2:39 | Cut to the terminal and run `bash ops/inspect_cloud_cluster.sh`. Keep the redacted JSON visible. | "The second submitted CockroachDB tool is the agent-ready ccloud CLI. This read-only JSON preflight verifies the Recant cluster, its AWS placement, plan, region, state, and version without exposing ids or SQL endpoints." |
| 2:39-2:50 | Return to the architecture diagram, then end on the repo and demo URLs. | "Bedrock supplies Titan embeddings and Claude affidavits. Lambda, EventBridge, S3, and KMS complete the production path. The code is at github.com/thamothara7/recant, and the repeatable demo is at recant.vercel.app." |

## Recording notes

- The Judge Overlay is evidence narration, not a claim that the public fixture
  is connected to a live cloud backend. Say "replay" or "shows" for console
  actions and reserve "verified" for the terminal preflight and repository
  checks.
- Keep the pointer still during the recant animation so the custody thread and
  status change remain legible in a paused frame.
- Upload to YouTube or Vimeo as **Public**, confirm the duration is below three
  minutes, open the link in a signed-out window, then paste it into Devpost.
