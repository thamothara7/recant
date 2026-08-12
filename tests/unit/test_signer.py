import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils

from services.attest_gateway.signer import (
    KMS_ECDSA_SHA256,
    KmsEcdsaSigner,
    dev_signer_for,
    verify_signature,
)

DIGEST = b"\xab" * 32


def test_dev_keys_are_deterministic_per_agent():
    assert (
        dev_signer_for("researcher").public_key_bytes()
        == dev_signer_for("researcher").public_key_bytes()
    )
    assert (
        dev_signer_for("researcher").public_key_bytes()
        != dev_signer_for("support").public_key_bytes()
    )


def test_sign_verify_roundtrip():
    s = dev_signer_for("researcher")
    sig = s.sign(DIGEST)
    assert verify_signature(s.public_key_bytes(), DIGEST, sig) is True


def test_tampered_digest_fails_verification():
    s = dev_signer_for("researcher")
    sig = s.sign(DIGEST)
    assert verify_signature(s.public_key_bytes(), b"\xcd" * 32, sig) is False


def test_wrong_key_fails_verification():
    sig = dev_signer_for("researcher").sign(DIGEST)
    assert verify_signature(dev_signer_for("support").public_key_bytes(), DIGEST, sig) is False


class _FakeKms:
    def __init__(self):
        self.key = ec.generate_private_key(ec.SECP256R1())

    def get_public_key(self, *, KeyId):
        return {
            "KeyId": KeyId,
            "SigningAlgorithms": ["ECDSA_SHA_256"],
            "PublicKey": self.key.public_key().public_bytes(
                serialization.Encoding.DER,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            ),
        }

    def sign(self, *, KeyId, Message, MessageType, SigningAlgorithm):
        assert KeyId == "arn:aws:kms:us-east-1:123:key/test"
        assert MessageType == "DIGEST"
        assert SigningAlgorithm == "ECDSA_SHA_256"
        return {"Signature": self.key.sign(Message, ec.ECDSA(utils.Prehashed(hashes.SHA256())))}


def test_kms_ecdsa_signatures_verify_offline():
    signer = KmsEcdsaSigner("arn:aws:kms:us-east-1:123:key/test", kms_client=_FakeKms())
    signature = signer.sign(DIGEST)
    assert verify_signature(signer.public_key_bytes(), DIGEST, signature, KMS_ECDSA_SHA256)


def test_development_signer_refuses_production(monkeypatch):
    monkeypatch.setenv("RECANT_ENV", "production")
    with pytest.raises(RuntimeError, match="refused"):
        dev_signer_for("researcher")
