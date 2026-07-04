"""Signing for attested writes.

Development signer only: keys are derived deterministically from the agent name so
the demo is reproducible (spec section 10). Production signing goes through AWS KMS
using agents.kms_key_arn (Week 4) behind the same sign(digest) interface; both sign
the 32-byte chain hash from chain.chain_hash.

dev_signer_for refuses to hand out deterministic dev keys when RECANT_ENV=production,
raising RuntimeError instead, so the demo signer can never be reached in a production
deployment by accident.
"""

import hashlib
import os

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


class Ed25519Signer:
    def __init__(self, private_key: Ed25519PrivateKey):
        self._key = private_key

    @classmethod
    def from_seed(cls, seed: bytes) -> "Ed25519Signer":
        return cls(Ed25519PrivateKey.from_private_bytes(hashlib.sha256(seed).digest()))

    def sign(self, digest: bytes) -> bytes:
        return self._key.sign(digest)

    def public_key_bytes(self) -> bytes:
        return self._key.public_key().public_bytes_raw()


def dev_signer_for(agent_name: str) -> Ed25519Signer:
    if os.environ.get("RECANT_ENV") == "production":
        raise RuntimeError("dev signer refused: RECANT_ENV=production")
    return Ed25519Signer.from_seed(f"recant-dev-key:{agent_name}".encode())


def dev_action_signer_for(actor: str) -> Ed25519Signer:
    """Signer for quarantine actions, in a keyspace DISJOINT from agent belief
    keys (domain separation). Actor is an unauthenticated request field: without
    separation a POST /recant with actor='researcher' would forge a signature
    that verifies under agent researcher's belief-chain pubkey (review
    2026-07-03). Actions verify against this namespace only; a registry that pins
    actor -> KMS key ARN replaces it in W4."""
    if os.environ.get("RECANT_ENV") == "production":
        raise RuntimeError("dev signer refused: RECANT_ENV=production")
    return Ed25519Signer.from_seed(f"recant-dev-action:{actor}".encode())


def verify_signature(public_key: bytes, digest: bytes, sig: bytes) -> bool:
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(sig, digest)
        return True
    except InvalidSignature:
        return False
