from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from services.common.attestation import sha256
from services.guard.crypto import action_digest, decode_permit, encode_permit, permit_payload
from services.guard.models import AuthorizeIn, ConsumeIn


def test_action_digest_is_canonical_for_arguments_and_support_order():
    tenant_id = uuid4()
    agent_id = uuid4()
    first, second = uuid4(), uuid4()
    left = action_digest(
        tenant_id=tenant_id,
        agent_id=agent_id,
        tool_name="refund",
        arguments={"amount": 25, "account": {"id": 42}},
        support_belief_ids=[first, second],
    )
    right = action_digest(
        tenant_id=tenant_id,
        agent_id=agent_id,
        tool_name="refund",
        arguments={"account": {"id": 42}, "amount": 25},
        support_belief_ids=[second, first],
    )
    assert left == right


def test_permit_envelope_round_trips_and_detects_payload_tamper():
    payload = permit_payload(
        permit_id=uuid4(),
        decision_id=uuid4(),
        tenant_id=uuid4(),
        agent_id=uuid4(),
        action_digest_value=sha256(b"action"),
        policy_version="test-v1",
        nonce=uuid4(),
        expires_at=datetime(2026, 8, 12, tzinfo=timezone.utc),
    )
    token = encode_permit(payload, b"signature")
    decoded, signature, document = decode_permit(token)
    assert decoded == payload
    assert signature == b"signature"
    assert document["type"] == "recant.action-permit.v1"

    prefix, encoded_payload, encoded_signature = token.split(".")
    replacement = "A" if encoded_payload[-1] != "A" else "B"
    tampered = ".".join((prefix, encoded_payload[:-1] + replacement, encoded_signature))
    with pytest.raises(ValueError, match="malformed"):
        decode_permit(tampered)


@pytest.mark.parametrize("model", [AuthorizeIn, ConsumeIn])
def test_action_models_reject_non_finite_arguments(model):
    common = {"arguments": {"amount": float("nan")}}
    payload = (
        {"agent_id": uuid4(), "tool_name": "refund", **common}
        if model is AuthorizeIn
        else {"permit": "x" * 32, "tool_name": "refund", **common}
    )
    with pytest.raises(ValidationError, match="finite JSON numbers"):
        model.model_validate(payload)
