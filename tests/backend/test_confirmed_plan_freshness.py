from __future__ import annotations

from dataclasses import replace

import pytest

from tunewise.plan_confirmation import (
    ConfirmedPlanFreshnessEvaluator,
    FreshnessBinding,
    deserialize_confirmed_plan,
    canonical_hash,
    confirmed_plan_business_payload,
)

from .test_plan_confirmation_api import _prepare_plan_ready
from .test_parameter_planning_api import make_planning_client


def _confirmed_plan(tmp_path):
    client, _app = make_planning_client(tmp_path)
    with client:
        task, planning = _prepare_plan_ready(client)
        candidate = planning["ordered_candidates"][0]
        response = client.post(
            f"/api/tasks/{task['task_id']}/confirmed-plans",
            json={
                "candidate_id": candidate["candidate_id"],
                "candidate_hash": candidate["candidate_hash"],
            },
        )
    return deserialize_confirmed_plan(response.json()["confirmed_plan"])


def _binding(plan):
    return FreshnessBinding(
        input_data_version=plan.input_data_version,
        input_measurement_hash=plan.input_measurement_hash,
        current_parameter_hash=plan.current_parameter_hash,
        detection_result_id=plan.detection_result_id,
        detection_result_version=plan.detection_result_version,
        diagnostic_result_id=plan.diagnostic_result_id,
        diagnostic_result_version=plan.diagnostic_result_version,
        case_retrieval_result_id=plan.case_retrieval_result_id,
        case_retrieval_result_version=plan.case_retrieval_result_version,
        planning_result_id=plan.planning_result_id,
        planning_result_version=plan.planning_result_version,
        candidate_hash=plan.candidate_hash,
        control_limit_snapshot_version=plan.control_limit_snapshot_version,
        control_limit_snapshot_hash=plan.control_limit_snapshot_hash,
        parameter_constraint_snapshot_version=plan.parameter_constraint_snapshot_version,
        parameter_constraint_snapshot_hash=plan.parameter_constraint_snapshot_hash,
        direction_rule_version=plan.direction_rule_version,
        safety_rule_version=plan.safety_rule_version,
        planning_rule_version=plan.planning_rule_version,
        rule_set_version=plan.rule_set_version,
        feature_definition_version=plan.feature_definition_version,
        model_version=plan.model_version,
        preprocessing_version=plan.preprocessing_version,
        approved_case_index_version=plan.approved_case_index_version,
        source_asset_hashes=plan.source_asset_hashes,
    )


@pytest.fixture(scope="module")
def shared_plan(tmp_path_factory):
    return _confirmed_plan(tmp_path_factory.mktemp("confirmed-plan"))


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"input_data_version": "changed"}, "INPUT_DATA_CHANGED"),
        ({"input_measurement_hash": "f" * 64}, "INPUT_DATA_CHANGED"),
        ({"current_parameter_hash": "f" * 64}, "CURRENT_PARAMETER_CHANGED"),
        ({"detection_result_id": "changed"}, "DETECTION_VERSION_CHANGED"),
        ({"detection_result_version": "changed"}, "DETECTION_VERSION_CHANGED"),
        ({"diagnostic_result_id": "changed"}, "DIAGNOSTIC_VERSION_CHANGED"),
        ({"case_retrieval_result_id": "changed"}, "RETRIEVAL_VERSION_CHANGED"),
        ({"planning_result_id": "changed"}, "PLANNING_VERSION_CHANGED"),
        ({"candidate_hash": "f" * 64}, "CANDIDATE_HASH_CHANGED"),
        ({"control_limit_snapshot_hash": "f" * 64}, "CONTROL_LIMIT_SNAPSHOT_CHANGED"),
        (
            {"parameter_constraint_snapshot_hash": "f" * 64},
            "PARAMETER_CONSTRAINT_SNAPSHOT_CHANGED",
        ),
        ({"direction_rule_version": "changed"}, "RULE_VERSION_CHANGED"),
        ({"safety_rule_version": "changed"}, "RULE_VERSION_CHANGED"),
        ({"planning_rule_version": "changed"}, "RULE_VERSION_CHANGED"),
        ({"model_version": "changed"}, "RULE_VERSION_CHANGED"),
    ],
)
def test_freshness_evaluator_reports_structured_reason(shared_plan, changes, reason) -> None:
    plan = shared_plan
    current = replace(_binding(plan), **changes)

    result = ConfirmedPlanFreshnessEvaluator().evaluate(plan, current)

    assert result.status == "STALE"
    assert reason in result.stale_reason_codes
    assert result.replay_eligible is False


def test_freshness_distinguishes_supporting_case_from_other_asset_changes(shared_plan) -> None:
    plan = shared_plan
    plan = replace(
        plan,
        source_asset_hashes={
            **plan.source_asset_hashes,
            "supporting_case:tw-approved-case-test": "a" * 64,
        },
    )
    binding = _binding(plan)
    other_assets = dict(binding.source_asset_hashes)
    other_assets["planning_asset_manifest"] = "f" * 64
    other = ConfirmedPlanFreshnessEvaluator().evaluate(
        plan, replace(binding, source_asset_hashes=other_assets)
    )
    case_assets = dict(binding.source_asset_hashes)
    case_key = next(key for key in case_assets if key.startswith("supporting_case:"))
    case_assets[case_key] = "f" * 64
    supporting_case = ConfirmedPlanFreshnessEvaluator().evaluate(
        plan, replace(binding, source_asset_hashes=case_assets)
    )

    assert other.stale_reason_codes == ("ASSET_HASH_MISMATCH",)
    assert supporting_case.stale_reason_codes == ("SUPPORTING_CASE_CHANGED",)


def test_stale_plan_cannot_be_restored_and_is_not_replay_eligible(shared_plan) -> None:
    plan = shared_plan
    binding = _binding(plan)
    stale = replace(
        plan,
        status="STALE",
        stale_reason_codes=("INPUT_DATA_CHANGED",),
    )

    result = ConfirmedPlanFreshnessEvaluator().evaluate(stale, binding)

    assert result.status == "STALE"
    assert result.stale_reason_codes == ("INPUT_DATA_CHANGED",)
    assert result.replay_eligible is False


def test_unknown_plan_status_fails_closed_for_replay(shared_plan) -> None:
    plan = replace(shared_plan, status="UNKNOWN", stale_reason_codes=())
    result = ConfirmedPlanFreshnessEvaluator().evaluate(plan, _binding(plan))

    assert result.status == "STALE"
    assert result.replay_eligible is False


def test_valid_plan_is_replay_eligible_through_reusable_entry_point(shared_plan) -> None:
    plan = shared_plan

    result = ConfirmedPlanFreshnessEvaluator().evaluate(plan, _binding(plan))

    assert result.status == "VALID"
    assert result.stale_reason_codes == ()
    assert result.replay_eligible is True


def test_confirmed_plan_hash_excludes_time_random_id_and_status(shared_plan) -> None:
    plan = shared_plan
    changed_metadata = replace(
        plan,
        confirmed_plan_id="random-database-id",
        confirmed_at="2099-01-01T00:00:00.000000Z",
        created_at="2099-01-01T00:00:00.000000Z",
        status="STALE",
        stale_reason_codes=("INPUT_DATA_CHANGED",),
    )

    assert canonical_hash(confirmed_plan_business_payload(changed_metadata)) == (
        plan.confirmed_plan_hash
    )


def test_confirmed_plan_binds_required_versions_snapshots_and_assets(shared_plan) -> None:
    plan = shared_plan

    assert plan.planning_result_id
    assert plan.planning_result_version == "tw-parameter-planning-result-v1"
    assert plan.detection_result_version == "tw-anomaly-detection-result-v1"
    assert plan.diagnostic_result_version == "tw-diagnostic-result-v1"
    assert plan.case_retrieval_result_version == "tw-case-retrieval-result-v1"
    assert plan.control_limit_snapshot_version == "tw-control-limits-v1"
    assert len(plan.control_limit_snapshot_hash) == 64
    assert plan.parameter_constraint_snapshot_version == "tw-parameter-constraints-v1"
    assert len(plan.parameter_constraint_snapshot_hash) == 64
    assert plan.direction_rule_version == "tw-direction-rules-v1"
    assert plan.safety_rule_version == "tw-parameter-safety-v1"
    assert plan.planning_rule_version == "tw-parameter-planning-v1"
    assert plan.rule_set_version == "tw-rules-v1"
    assert plan.feature_definition_version == "tw-feature-definition-v1"
    assert plan.model_version == "tw-model-v1"
    assert plan.preprocessing_version == "tw-preprocessing-v1"
    assert plan.approved_case_index_version == "tw-approved-case-index-v1"
    assert "planning_asset_manifest" in plan.source_asset_hashes
    assert "case_asset_manifest" in plan.source_asset_hashes


@pytest.mark.parametrize(
    "field",
    ["current_values", "proposed_values", "deltas", "delta_ticks", "source_asset_hashes"],
)
def test_confirmed_plan_nested_mappings_are_immutable(shared_plan, field) -> None:
    mapping = getattr(shared_plan, field)

    with pytest.raises(TypeError):
        mapping["tampered"] = "value"
