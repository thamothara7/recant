"""Conservative claim-relation verification for source-backed memories."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Literal, Protocol

RelationName = Literal["equivalent", "entails", "contradicts", "related", "unknown"]


@dataclass(frozen=True)
class ClaimRelation:
    relation: RelationName
    confidence: float
    method: str
    model: str | None
    version: str


class ClaimVerifier(Protocol):
    def verify(self, left: str, right: str) -> ClaimRelation: ...


def _normalized(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


class ConservativeClaimVerifier:
    """Offline verifier that emits evidence only for high-precision cases."""

    def verify(self, left: str, right: str) -> ClaimRelation:
        a = _normalized(left)
        b = _normalized(right)
        if a == b:
            return ClaimRelation("equivalent", 1.0, "exact_content", None, "v1")
        a_numbers = set(re.findall(r"\b\d+(?:\.\d+)?\b", a))
        b_numbers = set(re.findall(r"\b\d+(?:\.\d+)?\b", b))
        a_words = set(a.split()) - a_numbers
        b_words = set(b.split()) - b_numbers
        overlap = len(a_words & b_words) / max(len(a_words | b_words), 1)
        if a_numbers and b_numbers and a_numbers != b_numbers and overlap >= 0.5:
            return ClaimRelation("contradicts", 0.95, "numeric_contradiction", None, "v1")
        return ClaimRelation("unknown", 0.0, "conservative_heuristic", None, "v1")


class BedrockClaimVerifier:
    def __init__(self, client=None, model_id: str | None = None):
        self.model_id = model_id or os.environ.get(
            "RECANT_CLAIM_MODEL", "anthropic.claude-haiku-4-5-20251001-v1:0"
        )
        if client is None:  # pragma: no cover - exercised against AWS
            import boto3

            client = boto3.client(
                "bedrock-runtime", region_name=os.environ.get("AWS_REGION", "us-east-1")
            )
        self.client = client

    def verify(self, left: str, right: str) -> ClaimRelation:
        prompt = (
            "Classify the logical relation between two short memory claims. "
            "Return only JSON with relation one of equivalent, entails, contradicts, "
            "related, unknown and confidence from 0 to 1. Do not infer missing facts.\n"
            f"LEFT: {left}\nRIGHT: {right}"
        )
        response = self.client.converse(
            modelId=self.model_id,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"temperature": 0, "maxTokens": 100},
        )
        text = response["output"]["message"]["content"][0]["text"].strip()
        if text.startswith("```"):
            text = text.strip("`").removeprefix("json").strip()
        data = json.loads(text)
        relation = data.get("relation")
        confidence = float(data.get("confidence", 0))
        if relation not in {"equivalent", "entails", "contradicts", "related", "unknown"}:
            raise ValueError("claim verifier returned an unsupported relation")
        if not 0 <= confidence <= 1:
            raise ValueError("claim verifier confidence must be between 0 and 1")
        # Only high-confidence equivalence/entailment can expand taint closure.
        if relation in {"equivalent", "entails"} and confidence < 0.85:
            relation = "unknown"
        return ClaimRelation(relation, confidence, "bedrock_nli", self.model_id, "v1")


def select_claim_verifier() -> ClaimVerifier:
    name = os.environ.get("RECANT_CLAIM_VERIFIER", "conservative").lower()
    if name == "conservative":
        return ConservativeClaimVerifier()
    if name == "bedrock":
        return BedrockClaimVerifier()
    raise ValueError("RECANT_CLAIM_VERIFIER must be 'conservative' or 'bedrock'")
