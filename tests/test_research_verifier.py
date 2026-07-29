from sisyfus.research_v2.models import normalize_contract
from sisyfus.research_v2.verifier import classify_observation


def make_contract():
    return normalize_contract(
        {
            "id": "v",
            "target_claim_id": "c",
            "preconditions": {"all": [{"path": "metrics.ready", "op": "==", "value": True}]},
            "invalid_if": {"any": [{"path": "metrics.leakage", "op": "==", "value": True}]},
            "guardrails": {"all": [{"path": "metrics.cost", "op": "<=", "value": 1.0}]},
            "pass_if": {"all": [{"path": "metrics.score", "op": ">=", "value": 0.7}]},
            "fail_if": {"all": [{"path": "metrics.score", "op": "<", "value": 0.3}]},
            "required_artifacts": ["summary.json"],
        }
    )


def obs(**metrics):
    return {"metrics": metrics, "artifacts": [{"path": "summary.json", "sha256": "abc"}], "execution": {"exit_code": 0}}


def test_verifier_distinguishes_all_five_outcomes():
    contract = make_contract()
    assert classify_observation(contract, obs(ready=True, leakage=False, cost=0.2, score=0.8))["status"] == "PASS"
    assert classify_observation(contract, obs(ready=True, leakage=False, cost=0.2, score=0.1))["status"] == "FAIL"
    assert classify_observation(contract, obs(ready=True, leakage=False, cost=0.2, score=0.5))["status"] == "INCONCLUSIVE"
    assert classify_observation(contract, obs(ready=True, leakage=True, cost=0.2, score=0.8))["status"] == "INVALID"
    assert classify_observation(contract, {"execution": {"error": "boom"}})["status"] == "ERROR"


def test_guardrail_failure_is_valid_fail_and_missing_artifact_is_invalid():
    contract = make_contract()
    assert classify_observation(contract, obs(ready=True, leakage=False, cost=2.0, score=0.8))["reason_code"] == "guardrail_failed"
    result = classify_observation(contract, {"metrics": {"ready": True, "score": 0.8, "cost": 0.1}})
    assert result["status"] == "INVALID"
    assert result["reason_code"] == "required_artifact_missing"
