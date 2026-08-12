from services.taint_engine.relations import BedrockClaimVerifier, ConservativeClaimVerifier


def test_conservative_verifier_accepts_only_exact_normalized_equivalence():
    result = ConservativeClaimVerifier().verify("Refund window: 30 days.", "refund window 30 days")
    assert result.relation == "equivalent"
    assert result.confidence == 1.0


def test_conservative_verifier_marks_numeric_conflict_without_spreading_taint():
    result = ConservativeClaimVerifier().verify(
        "The refund window is 30 days", "The refund window is 365 days"
    )
    assert result.relation == "contradicts"
    assert result.confidence == 0.95


class _FakeBedrock:
    def converse(self, **kwargs):
        return {
            "output": {
                "message": {"content": [{"text": '{"relation":"entails","confidence":0.6}'}]}
            }
        }


def test_bedrock_verifier_downgrades_weak_entailment():
    result = BedrockClaimVerifier(client=_FakeBedrock(), model_id="fake-model").verify(
        "left", "right"
    )
    assert result.relation == "unknown"
    assert result.confidence == 0.6
