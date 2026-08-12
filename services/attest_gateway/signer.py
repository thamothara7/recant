"""Signing backends for custody records and control-plane decisions.

Local development keeps deterministic Ed25519 keys so the fixture demo remains
reproducible. Production requires asymmetric AWS KMS keys and signs the same
32-byte digests with ECDSA_SHA_256. Stored rows carry the algorithm, public key,
and key identifier so verification never depends on mutable runtime settings.
"""

from __future__ import annotations

import hashlib
import os
from functools import lru_cache
from typing import Protocol

from cryptography import exceptions as crypto_exceptions
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, utils

ED25519 = "ed25519"
KMS_ECDSA_SHA256 = "aws-kms-ecdsa-sha256"


class Signer(Protocol):
    algorithm: str
    key_id: str

    def sign(self, digest: bytes) -> bytes: ...

    def public_key_bytes(self) -> bytes: ...


class Ed25519Signer:
    algorithm = ED25519

    def __init__(self, private_key: ed25519.Ed25519PrivateKey, *, key_id: str = "development"):
        self._key = private_key
        self.key_id = key_id

    @classmethod
    def from_seed(cls, seed: bytes, *, key_id: str = "development") -> "Ed25519Signer":
        key = ed25519.Ed25519PrivateKey.from_private_bytes(hashlib.sha256(seed).digest())
        return cls(key, key_id=key_id)

    def sign(self, digest: bytes) -> bytes:
        if len(digest) != 32:
            raise ValueError("signers accept a 32-byte SHA-256 digest")
        return self._key.sign(digest)

    def public_key_bytes(self) -> bytes:
        return self._key.public_key().public_bytes_raw()


class KmsEcdsaSigner:
    algorithm = KMS_ECDSA_SHA256

    def __init__(self, key_id: str, *, kms_client=None):
        if not key_id:
            raise ValueError("an AWS KMS key ARN is required")
        self.key_id = key_id
        if kms_client is None:  # pragma: no cover - exercised with AWS credentials
            import boto3

            kms_client = boto3.client("kms")
        self._kms = kms_client
        metadata = self._kms.get_public_key(KeyId=key_id)
        algorithms = metadata.get("SigningAlgorithms", [])
        if "ECDSA_SHA_256" not in algorithms:
            raise ValueError(f"KMS key {key_id} does not support ECDSA_SHA_256")
        self._public_key = bytes(metadata["PublicKey"])

    def sign(self, digest: bytes) -> bytes:
        if len(digest) != 32:
            raise ValueError("signers accept a 32-byte SHA-256 digest")
        result = self._kms.sign(
            KeyId=self.key_id,
            Message=digest,
            MessageType="DIGEST",
            SigningAlgorithm="ECDSA_SHA_256",
        )
        return bytes(result["Signature"])

    def public_key_bytes(self) -> bytes:
        return self._public_key


def _production() -> bool:
    return os.environ.get("RECANT_ENV", "").strip().lower() == "production"


def dev_signer_for(agent_name: str) -> Ed25519Signer:
    if _production():
        raise RuntimeError("development signer refused in production")
    return Ed25519Signer.from_seed(
        f"recant-dev-key:{agent_name}".encode(),
        key_id=f"development:agent:{agent_name}",
    )


def dev_action_signer_for(actor: str) -> Ed25519Signer:
    """Domain-separated development signer retained for stored demo evidence."""
    if _production():
        raise RuntimeError("development signer refused in production")
    return Ed25519Signer.from_seed(
        f"recant-dev-action:{actor}".encode(),
        key_id=f"development:control:{actor}",
    )


@lru_cache(maxsize=128)
def _kms_signer(key_id: str) -> KmsEcdsaSigner:
    return KmsEcdsaSigner(key_id)


def signer_for_agent(agent_name: str, kms_key_arn: str | None) -> Signer:
    if kms_key_arn:
        return _kms_signer(kms_key_arn)
    if _production():
        raise RuntimeError("production agents require kms_key_arn")
    return dev_signer_for(agent_name)


def control_signer_for(purpose: str) -> Signer:
    key_id = os.environ.get("RECANT_CONTROL_KMS_KEY_ARN")
    if key_id:
        return _kms_signer(key_id)
    if _production():
        raise RuntimeError("RECANT_CONTROL_KMS_KEY_ARN is required in production")
    return dev_action_signer_for(purpose)


def quarantine_signer_for(actor: str) -> Signer:
    """Keep actor-specific development evidence while using one pinned KMS key."""
    if _production() or os.environ.get("RECANT_CONTROL_KMS_KEY_ARN"):
        return control_signer_for("quarantine")
    return dev_action_signer_for(actor)


def verify_signature(
    public_key: bytes,
    digest: bytes,
    sig: bytes,
    algorithm: str = ED25519,
) -> bool:
    try:
        if algorithm == ED25519:
            ed25519.Ed25519PublicKey.from_public_bytes(public_key).verify(sig, digest)
            return True
        if algorithm == KMS_ECDSA_SHA256:
            key = serialization.load_der_public_key(public_key)
            if not isinstance(key, ec.EllipticCurvePublicKey):
                return False
            key.verify(sig, digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
            return True
        return False
    except (ValueError, TypeError, crypto_exceptions.InvalidSignature):
        return False
