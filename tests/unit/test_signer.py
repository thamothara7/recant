from services.attest_gateway.signer import Ed25519Signer, dev_signer_for, verify_signature

DIGEST = b"\xab" * 32


def test_dev_keys_are_deterministic_per_agent():
    assert dev_signer_for("researcher").public_key_bytes() == dev_signer_for("researcher").public_key_bytes()
    assert dev_signer_for("researcher").public_key_bytes() != dev_signer_for("support").public_key_bytes()


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
