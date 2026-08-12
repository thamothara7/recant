from uuid import uuid4

import pytest
from pydantic import ValidationError

from services.attest_gateway.models import BeliefIn
from services.common.embedder import DIMENSIONS


@pytest.mark.parametrize("component", [float("nan"), float("inf"), float("-inf")])
def test_belief_rejects_non_finite_embedding(component):
    embedding = [0.1] * DIMENSIONS
    embedding[17] = component
    with pytest.raises(ValidationError, match="finite values"):
        BeliefIn(agent_id=uuid4(), content="claim", embedding=embedding)


def test_belief_rejects_zero_embedding():
    with pytest.raises(ValidationError, match="all zero"):
        BeliefIn(agent_id=uuid4(), content="claim", embedding=[0.0] * DIMENSIONS)
