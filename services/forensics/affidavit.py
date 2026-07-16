"""Affidavit generators behind one dispatcher (W4; Bedrock leg of U3).

Two generators produce the incident affidavit from the same structured data:

- template: deterministic text template, the offline default. Tests and the
  local demo never need AWS, and it is the fallback whenever Bedrock errors.
- bedrock: Claude via the Bedrock converse API (RECANT_AFFIDAVIT=bedrock).
  The prompt embeds the structured facts as JSON and instructs the model to
  state only those facts; temperature 0. The boto3 client is lazy and
  injectable, mirroring TitanEmbedder: importing and selecting never touch AWS.

generate_affidavit() is the single entry point: it dispatches on env and
returns (text, generated_by) where generated_by is "template" or the model id.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from services.common.logging import configure

log = configure("forensics.affidavit")

# The us. prefix is a cross-region inference profile: Bedrock rejects bare
# Anthropic model IDs for on-demand throughput ("Invocation of model ID ...
# isn't supported. Retry ... with an inference profile"), verified live Jul 16.
DEFAULT_MODEL = "us.anthropic.claude-haiku-4-5-20251001-v1:0"


# ---------------------------------------------------------------------------
# template generator (moved verbatim from app.py; the offline default)
# ---------------------------------------------------------------------------

def generate_affidavit_text(
    *,
    incident_id,
    created_at: datetime,
    opened_by: str,
    source_id,
    source_kind: str,
    source_uri: str,
    source_trust_tier: str,
    belief_count: int,
    agents_affected: list[dict],
    actions: list[dict],
    events: list[dict],
) -> str:
    """Generate a text-template incident affidavit from structured data.

    Standalone so unit tests can exercise it without a database, and kept as
    the fallback when the Bedrock generator is unavailable.
    """
    lines = [
        "INCIDENT AFFIDAVIT",
        "==================",
        f"Incident ID: {incident_id}",
        f"Opened:      {created_at.strftime('%Y-%m-%d %H:%M:%S')} UTC",
        f"Opened by:   {opened_by}",
        "",
        "SOURCE",
        "------",
        f"Source ID:   {source_id}",
        f"Kind:        {source_kind}",
        f"URI:         {source_uri}",
        f"Trust tier:  {source_trust_tier}",
        "",
        "IMPACT",
        "------",
        f"{belief_count} belief(s) quarantined across {len(agents_affected)} agent(s).",
        "",
    ]
    for agent in agents_affected:
        lines.append(
            f"  Agent \"{agent['agent_name']}\": {agent['belief_count']} belief(s) quarantined"
        )

    lines.extend(["", "QUARANTINE ACTIONS", "------------------"])
    if not actions:
        lines.append("  (none recorded)")
    for act in actions:
        lines.append(f"  Action ID:  {act['action_id']}")
        lines.append(f"  Signature:  {act['sig'][:16]}... ({act['sig_status']})")
        lines.append(f"  Flipped:    {act['belief_count']} belief(s)")
        lines.append("")

    lines.extend(["EVENTS TIMELINE", "---------------"])
    if not events:
        lines.append("  (no events recorded)")
    for evt in events:
        if isinstance(evt["created_at"], datetime):
            ts = evt["created_at"].strftime("%H:%M:%S")
        else:
            ts = str(evt["created_at"])
        lines.append(f"  {ts} | {evt['kind']} | {evt.get('summary', '')}")

    lines.extend([
        "",
        "---",
        "This affidavit was generated from database records using a text template.",
        "",
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC",
    ])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# bedrock generator
# ---------------------------------------------------------------------------

_SYSTEM = (
    "You are a forensic scribe for an agent-memory custody system. You write "
    "formal incident affidavits from structured database records. State only "
    "facts present in the provided JSON; never invent, estimate, or embellish. "
    "Reproduce every ID, count, timestamp, and signature status verbatim. If a "
    "quarantine action's sig_status is INVALID, state plainly that the action "
    "record failed signature verification and must not be relied upon. Plain "
    "text only: no markdown, no em-dashes, no emojis. At most 350 words. Begin "
    "with the line 'INCIDENT AFFIDAVIT' and end with a one-sentence attestation "
    "that the affidavit was derived solely from the records presented."
)


class BedrockAffidavitGenerator:
    """Claude affidavit writer over bedrock-runtime converse (lazy client)."""

    def __init__(self, client=None, model_id: str | None = None):
        self._client = client
        self.model_id = model_id or os.environ.get(
            "RECANT_AFFIDAVIT_MODEL", DEFAULT_MODEL
        )

    def _bedrock(self):
        if self._client is None:
            import boto3

            region = (
                os.environ.get("AWS_REGION")
                or os.environ.get("AWS_DEFAULT_REGION")
                or "us-east-1"
            )
            self._client = boto3.client("bedrock-runtime", region_name=region)
        return self._client

    def generate(self, structured: dict) -> str:
        prompt = (
            "Write the incident affidavit for these records:\n\n"
            + json.dumps(structured, default=str, indent=2)
        )
        resp = self._bedrock().converse(
            modelId=self.model_id,
            system=[{"text": _SYSTEM}],
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": 1024, "temperature": 0},
        )
        text = resp["output"]["message"]["content"][0]["text"].strip()
        if "INCIDENT AFFIDAVIT" not in text:
            raise ValueError("model response is not an affidavit")
        return text


# ---------------------------------------------------------------------------
# dispatcher
# ---------------------------------------------------------------------------

def generate_affidavit(structured: dict, *, bedrock_client=None) -> tuple[str, str]:
    """Produce (text, generated_by) for the affidavit endpoint.

    RECANT_AFFIDAVIT selects the generator: 'template' (default) or 'bedrock'.
    A Bedrock failure falls back to the template so the judge-facing endpoint
    keeps answering; the fallback is visible in generated_by and the log.
    """
    mode = os.environ.get("RECANT_AFFIDAVIT", "template")
    if mode == "bedrock":
        gen = BedrockAffidavitGenerator(client=bedrock_client)
        try:
            return gen.generate(structured), gen.model_id
        except Exception as exc:
            log.warning(
                "bedrock affidavit failed, falling back to template",
                extra={"fields": {"error": str(exc)[:200]}},
            )
            return generate_affidavit_text(**structured), "template (bedrock error)"
    if mode != "template":
        raise ValueError(f"unknown RECANT_AFFIDAVIT: {mode!r}")
    return generate_affidavit_text(**structured), "template"
