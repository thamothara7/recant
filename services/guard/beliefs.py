"""Verification of memory evidence before Guard assigns it authority."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import psycopg

from services.attest_gateway import chain
from services.attest_gateway.signer import signer_for_agent, verify_signature


class BeliefVerificationError(RuntimeError):
    """A persisted belief no longer matches its signed attestation."""


class BeliefTrustUnavailable(RuntimeError):
    """The configured signer needed to establish trust is unavailable."""


@dataclass(frozen=True)
class VerifiedBelief:
    belief_id: UUID
    hash_hex: str
    status: str
    authority_rank: int
    origin_source_ids: list[UUID]


def load_verified_beliefs(
    conn: psycopg.Connection,
    *,
    tenant_id: UUID,
    belief_ids: list[UUID],
) -> list[VerifiedBelief]:
    """Load beliefs and verify their hash, signature, and configured signer.

    Historical v1 attestations did not bind authority or tenant provenance, so
    they deliberately contribute zero authority even when their legacy content
    signature is valid. New v2 records bind every field Guard relies on.
    """
    if not belief_ids:
        return []
    rows = conn.execute(
        "SELECT b.belief_id, b.agent_id, b.seq, b.content, b.source_id, b.created_at,"
        " b.sig, b.prev_hash, b.hash, b.status, b.context_receipt_id, b.authority_rank,"
        " b.origin_source_ids, b.provenance_method, b.provenance_version,"
        " b.attestation_version, a.name, a.pubkey, a.kms_key_arn, a.signing_algorithm,"
        " (SELECT array_agg(d.parent_id ORDER BY d.parent_id) FROM derivations d"
        "  WHERE d.tenant_id = b.tenant_id AND d.child_id = b.belief_id"
        "    AND d.kind = 'explicit')"
        " FROM beliefs b JOIN agents a"
        " ON a.tenant_id = b.tenant_id AND a.agent_id = b.agent_id"
        " WHERE b.tenant_id = %s AND b.belief_id = ANY(%s) ORDER BY b.belief_id",
        (tenant_id, belief_ids),
    ).fetchall()

    verified: list[VerifiedBelief] = []
    for row in rows:
        belief_id = row[0]
        try:
            trusted_signer = signer_for_agent(row[16], row[18])
        except (RuntimeError, ValueError) as exc:
            raise BeliefTrustUnavailable(str(exc)) from exc
        trusted_pubkey = trusted_signer.public_key_bytes()
        if row[19] != trusted_signer.algorithm or bytes(row[17]) != trusted_pubkey:
            raise BeliefVerificationError(f"belief {belief_id} has an untrusted signer")

        record = chain.ChainRecord(
            agent_id=row[1],
            seq=int(row[2]),
            content=row[3],
            source_id=row[4],
            parent_ids=list(row[20] or []),
            ts=row[5],
            prev_hash=bytes(row[7]),
            hash=bytes(row[8]),
            tenant_id=tenant_id,
            context_receipt_id=row[10],
            authority_rank=int(row[11]),
            origin_source_ids=list(row[12] or []),
            provenance_method=row[13],
            provenance_version=row[14],
            attestation_version=row[15],
        )
        try:
            expected_hash = chain.chain_hash(record.prev_hash, chain.record_payload(record))
        except ValueError as exc:
            raise BeliefVerificationError(
                f"belief {belief_id} has an unsupported attestation"
            ) from exc
        if expected_hash != record.hash or not verify_signature(
            trusted_pubkey,
            record.hash,
            bytes(row[6]),
            trusted_signer.algorithm,
        ):
            raise BeliefVerificationError(f"belief {belief_id} failed attestation verification")

        effective_authority = record.authority_rank if record.attestation_version == "v2" else 0
        verified.append(
            VerifiedBelief(
                belief_id=belief_id,
                hash_hex=record.hash.hex(),
                status=row[9],
                authority_rank=effective_authority,
                origin_source_ids=list(record.origin_source_ids or []),
            )
        )
    return verified
