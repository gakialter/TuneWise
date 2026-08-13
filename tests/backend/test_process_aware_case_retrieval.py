from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import asdict, replace
from decimal import Decimal, ROUND_HALF_EVEN
from pathlib import Path

import pytest

from tools.generate_approved_case_index import generate as generate_cases
from tunewise.case_retrieval import (
    DISTANCE_PRECISION,
    ApprovedCase,
    ApprovedCaseAssetLoader,
    StructuredCaseRetriever,
)
from tunewise.diagnosis import DerivedFeatureSet
from tunewise.diagnostic_contract import FEATURE_DEFINITION_VERSION, FEATURE_NAMES
from tunewise.parameter_planning import (
    HistoricalCaseAction,
    ParameterPlanGenerator,
)
from tunewise.process_aware_retrieval import (
    PROCESS_AWARE_RETRIEVAL_RESULT_VERSION,
    ProcessAwareCaseRetrievalDecision,
    ProcessAwareCaseRetriever,
    ProcessAwareParameterPlanGenerator,
)
from tunewise.process_context import (
    PROCESS_CONTEXT_SCHEMA_VERSION,
    ContextCompatibilityEvaluator,
    PreviousActionOutcome,
    PreviousParameterAction,
    ProcessContext,
    ProcessContextProvenance,
    ProcessContextSource,
    ProcessContextValidationError,
    ProcessStage,
    case_process_profile_from_payload,
    process_context_from_payload,
)

from .test_parameter_plan_generation import _evidence, _snapshot, _values
from .test_parameter_planning_api import _prepare, make_planning_client


FIXTURE_PATH = (
    Path(__file__).parents[1]
    / "fixtures"
    / "process-context"
    / "process-aware-cases-v1.json"
)
TOP3 = ("PLANE_TILT", "XY_DECENTER", "REFERENCE_DRIFT")


def _fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _assets(tmp_path):
    root = tmp_path / "cases"
    generate_cases(root, seed=20260718)
    manifest_hash = hashlib.sha256((root / "manifest.json").read_bytes()).hexdigest()
    return ApprovedCaseAssetLoader(root, manifest_hash).load()


def _query(case: ApprovedCase) -> DerivedFeatureSet:
    return DerivedFeatureSet(
        feature_definition_version=FEATURE_DEFINITION_VERSION,
        feature_names=FEATURE_NAMES,
        values=tuple(float(value) for value in case.feature_values),
        input_feature_hash="a" * 64,
    )


def _historical(case: ApprovedCase) -> HistoricalCaseAction:
    action = case.historical_action
    result = case.historical_simulated_result
    return HistoricalCaseAction(
        case_id=case.case_id,
        status=case.status,
        source_partition=case.source_partition,
        source_partition_id=case.source_partition_id,
        station_type=case.station_type,
        product_model=case.product_model,
        reviewed_root_cause=case.reviewed_root_cause,
        parameter_family=case.parameter_family or "",
        parameter_delta_ticks=dict(action["parameter_delta_ticks"]),
        action_version=action["action_version"],
        historical_safety_status=action["historical_safety_status"],
        historical_safety_rule_version=action["historical_safety_rule_version"],
        historical_simulated_result_status=result["status"],
        center_within_tolerance=result["center_within_tolerance"],
        feature_definition_version=case.feature_definition_version,
        rule_set_version=case.rule_set_version,
        retrieval_rule_version=case.retrieval_rule_version,
        case_schema_version=case.case_schema_version,
    )


def _load_process_fixture():
    payload = _fixture()
    contexts = {
        name: process_context_from_payload(item)
        for name, item in payload["contexts"].items()
    }
    profiles = tuple(
        case_process_profile_from_payload(item)
        for item in payload["case_process_profiles"]
    )
    return payload, contexts, profiles


def _evaluation(decision: ProcessAwareCaseRetrievalDecision, case_id: str):
    return next(item for item in decision.case_evaluations if item.case_id == case_id)


def _candidate(decision, generation_type: str):
    return next(
        item
        for item in decision.ordered_candidates
        if item.generation_type == generation_type
    )


def test_process_context_is_immutable_versioned_canonical_and_synthetic() -> None:
    payload, contexts, profiles = _load_process_fixture()
    first = contexts["scenario_b"]
    second = process_context_from_payload(payload["contexts"]["scenario_b"])

    assert first.schema_version == PROCESS_CONTEXT_SCHEMA_VERSION
    assert first.context_hash == second.context_hash
    assert first.canonical_json() == second.canonical_json()
    assert first.is_synthetic
    assert all(profile.is_synthetic for profile in profiles)
    assert "SYNTHETIC_TEST_FIXTURE" in first.canonical_json()
    assert "production evidence" in payload["facts_boundary"]
    with pytest.raises((AttributeError, TypeError)):
        first.iteration_index = 2


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"iteration_index": 1}, "INITIAL_PROCESS_CONTEXT_INVALID"),
        (
            {"previous_measurement_hash": "a" * 64},
            "INITIAL_PROCESS_CONTEXT_INVALID",
        ),
    ],
)
def test_initial_assessment_rejects_fabricated_previous_state(overrides, code) -> None:
    provenance = ProcessContextProvenance(
        source_kind=ProcessContextSource.SYNTHETIC_TEST_FIXTURE,
        source_refs=("unit-test",),
        source_hashes=("a" * 64,),
        actor_id="synthetic-test-fixture",
        recorded_at="2026-08-11T00:00:00+08:00",
    )
    values = {
        "process_stage": ProcessStage.INITIAL_ASSESSMENT,
        "iteration_index": 0,
        "previous_measurement_hash": None,
        "previous_action": None,
        "previous_action_outcome": None,
        "outcome_rule_version": None,
        "provenance": provenance,
        **overrides,
    }
    with pytest.raises(ProcessContextValidationError, match="previous state") as error:
        ProcessContext(**values)
    assert error.value.code == code


def test_previous_action_enforces_decimal_math_pairs_and_runtime_evidence() -> None:
    action = PreviousParameterAction(
        parameter_name="pitch",
        before_value="0.250000",
        after_value="0.200000",
        delta_ticks=-1,
        action_version="tw-approved-case-action-v1",
        confirmed_plan_id="tw-confirmed-plan-test",
        confirmed_plan_hash="a" * 64,
        execution_receipt_id="tw-device-execution-test",
        execution_receipt_hash="b" * 64,
    )
    action.verify_runtime_evidence(
        confirmed_plan={
            "confirmed_plan_id": "tw-confirmed-plan-test",
            "confirmed_plan_hash": "a" * 64,
            "current_values": {"pitch": "0.250000"},
            "proposed_values": {"pitch": "0.200000"},
            "delta_ticks": {"pitch": -1},
        },
        execution_receipt={
            "device_execution_id": "tw-device-execution-test",
            "receipt_hash": "b" * 64,
            "parameter_name": "pitch",
            "actual_before_value": "0.250000",
            "actual_after_value": "0.200000",
            "tick_delta": -1,
        },
    )
    with pytest.raises(ProcessContextValidationError) as mismatch:
        action.verify_runtime_evidence(
            confirmed_plan={
                "confirmed_plan_id": "tw-confirmed-plan-test",
                "confirmed_plan_hash": "a" * 64,
                "current_values": {"pitch": "0.250000"},
                "proposed_values": {"pitch": "0.150000"},
                "delta_ticks": {"pitch": -2},
            }
        )
    assert mismatch.value.code == "PREVIOUS_ACTION_RUNTIME_EVIDENCE_MISMATCH"

    with pytest.raises(ProcessContextValidationError) as arithmetic:
        PreviousParameterAction(
            parameter_name="pitch",
            before_value="0.250000",
            after_value="0.150000",
            delta_ticks=-1,
            action_version="tw-approved-case-action-v1",
        )
    assert arithmetic.value.code == "PREVIOUS_ACTION_DELTA_MISMATCH"


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("iteration_index", 0, "POST_ADJUSTMENT_PROCESS_CONTEXT_INVALID"),
        ("previous_measurement_hash", None, "POST_ADJUSTMENT_PROCESS_CONTEXT_INVALID"),
        ("previous_action", None, "POST_ADJUSTMENT_PROCESS_CONTEXT_INVALID"),
        ("previous_action_outcome", None, "POST_ADJUSTMENT_PROCESS_CONTEXT_INVALID"),
        ("outcome_rule_version", None, "OUTCOME_RULE_VERSION_REQUIRED"),
    ],
)
def test_post_adjustment_requires_previous_state_and_versioned_outcome(
    field, value, code
) -> None:
    payload = deepcopy(_fixture()["contexts"]["scenario_b"])
    payload[field] = value
    with pytest.raises(ProcessContextValidationError) as error:
        process_context_from_payload(payload)
    assert error.value.code == code


def test_not_evaluable_is_the_only_unversioned_outcome_and_reasons_are_stable() -> None:
    fixture_payload, contexts, profiles = _load_process_fixture()
    not_evaluable_payload = deepcopy(fixture_payload["contexts"]["scenario_b"])
    not_evaluable_payload["previous_action_outcome"] = "NOT_EVALUABLE"
    not_evaluable_payload["outcome_rule_version"] = None
    assert (
        process_context_from_payload(not_evaluable_payload).previous_action_outcome
        is PreviousActionOutcome.NOT_EVALUABLE
    )

    invalid = deepcopy(not_evaluable_payload)
    invalid["outcome_rule_version"] = "tw-synthetic-outcome-rule-v1"
    with pytest.raises(ProcessContextValidationError) as error:
        process_context_from_payload(invalid)
    assert error.value.code == "NOT_EVALUABLE_OUTCOME_RULE_FORBIDDEN"

    post_profile = next(
        profile for profile in profiles if profile.case_id == "tw-aa-approved-003"
    )
    outcome_payload = deepcopy(fixture_payload["contexts"]["scenario_b"])
    outcome_payload["previous_action_outcome"] = "IMPROVED"
    evaluator = ContextCompatibilityEvaluator()
    outcome_decision = evaluator.evaluate(
        process_context_from_payload(outcome_payload), post_profile
    )
    assert outcome_decision.reason_code.value == "PREVIOUS_OUTCOME_MISMATCH"

    iteration_payload = deepcopy(fixture_payload["contexts"]["scenario_b"])
    iteration_payload["iteration_index"] = 2
    iteration_decision = evaluator.evaluate(
        process_context_from_payload(iteration_payload), post_profile
    )
    assert iteration_decision.reason_code.value == "ITERATION_OUT_OF_RANGE"


def test_process_aware_decision_consistency_and_candidate_boundaries(tmp_path) -> None:
    assets = _assets(tmp_path)
    fixture_payload, contexts, profiles = _load_process_fixture()
    by_id = {case.case_id: case for case in assets.cases}
    query = _query(by_id["tw-aa-approved-011"])
    retriever = ProcessAwareCaseRetriever(assets, profiles)

    scenario_a = retriever.retrieve(
        query_features=query,
        product_model="TW-AA-PROTOTYPE-V1",
        top3_root_causes=TOP3,
        top_k=3,
        process_context=contexts["scenario_a"],
    )
    scenario_b = retriever.retrieve(
        query_features=query,
        product_model="TW-AA-PROTOTYPE-V1",
        top3_root_causes=TOP3,
        top_k=3,
        process_context=contexts["scenario_b"],
    )
    assert isinstance(scenario_a, ProcessAwareCaseRetrievalDecision)
    assert isinstance(scenario_b, ProcessAwareCaseRetrievalDecision)
    assert scenario_a.context_is_synthetic and scenario_b.context_is_synthetic
    assert scenario_a.context_source_kind == "SYNTHETIC_TEST_FIXTURE"
    assert _evaluation(scenario_a, "tw-aa-approved-011").profile_is_synthetic

    # Classifier/scaler inputs and Top-3 are fixed; only ProcessContext changed.
    assert scenario_a.query_feature_hash == scenario_b.query_feature_hash == query.input_feature_hash
    assert scenario_a.ordered_top3_root_causes == scenario_b.ordered_top3_root_causes == TOP3
    assert scenario_a.product_model == scenario_b.product_model == "TW-AA-PROTOTYPE-V1"
    assert scenario_a.feature_definition_version == scenario_b.feature_definition_version
    assert scenario_a.scaler_version == scenario_b.scaler_version
    assert scenario_a.case_index_hash == scenario_b.case_index_hash

    assert scenario_a.eligible_case_ids == ("tw-aa-approved-011",)
    assert scenario_b.eligible_case_ids == ("tw-aa-approved-003",)
    assert _evaluation(scenario_a, "tw-aa-approved-011").reason_code == "CONTEXT_MATCH"
    assert _evaluation(scenario_b, "tw-aa-approved-011").reason_code == "PROCESS_STAGE_MISMATCH"
    assert _evaluation(scenario_b, "tw-aa-approved-001").reason_code == "PREVIOUS_ACTION_PARAMETER_MISMATCH"
    legacy_case_id = fixture_payload["legacy_context_unavailable_case_ids"][0]
    assert _evaluation(scenario_b, legacy_case_id).reason_code == "CASE_CONTEXT_UNAVAILABLE"
    assert legacy_case_id in scenario_b.informational_only_case_ids
    assert legacy_case_id not in scenario_b.eligible_case_ids

    # The process filter does not alter the existing fixed-precision distance formula.
    for decision in (scenario_a, scenario_b):
        retrieved = decision.ordered_cases[0]
        case = by_id[retrieved.case_id]
        query_values = tuple(Decimal(f"{value:.12f}") for value in query.values)
        expected = sum(
            (
                ((query_value - case_value) / scale) ** 2
                for query_value, case_value, scale in zip(
                    query_values,
                    case.feature_values,
                    assets.scaler_scale,
                    strict=True,
                )
            ),
            Decimal(0),
        ).sqrt().quantize(DISTANCE_PRECISION, rounding=ROUND_HALF_EVEN)
        assert retrieved.distance == f"{expected:.6f}"

    planning_cases = tuple(
        _historical(by_id[case_id])
        for case_id in ("tw-aa-approved-011", "tw-aa-approved-003", "tw-aa-approved-001", "tw-aa-approved-008")
    )
    planner = ProcessAwareParameterPlanGenerator(ParameterPlanGenerator())
    planning_args = {
        "root_cause": "PLANE_TILT",
        "parameter_family": "PITCH_ROLL",
        "current_values": _values(),
        "direction_evidence": (_evidence("pitch", 5),),
        "snapshot": _snapshot(),
        "diagnostic_result_version": "tw-diagnostic-result-v1",
        "cases": planning_cases,
        "feature_definition_version": FEATURE_DEFINITION_VERSION,
        "product_model": "TW-AA-PROTOTYPE-V1",
    }
    plan_a = planner.generate(retrieval=scenario_a, **planning_args)
    plan_b = planner.generate(retrieval=scenario_b, **planning_args)

    conservative_a = _candidate(plan_a, "CONSERVATIVE")
    conservative_b = _candidate(plan_b, "CONSERVATIVE")
    standard_a = _candidate(plan_a, "STANDARD")
    standard_b = _candidate(plan_b, "STANDARD")
    assert asdict(conservative_a) == asdict(conservative_b)
    assert asdict(standard_a) == asdict(standard_b)
    assert _candidate(plan_a, "CASE_GUIDED").supporting_case_ids == (
        "tw-aa-approved-011",
    )
    assert _candidate(plan_b, "CASE_GUIDED").supporting_case_ids == (
        "tw-aa-approved-003",
    )
    assert _candidate(plan_a, "CASE_GUIDED").delta_ticks == {"pitch": -3}
    assert _candidate(plan_b, "CASE_GUIDED").delta_ticks == {"pitch": -4}

    # Every candidate still contains the unchanged unified safety-validator evidence.
    for plan in (plan_a, plan_b):
        assert all(item.validation_status == "PASSED" for item in plan.ordered_candidates)
        assert all(
            {check.check_code for check in item.validation_checks}
            == {check.check_code for check in conservative_a.validation_checks}
            for item in plan.ordered_candidates
        )

    # Same scenario repeated twice is identical, including explanations and hashes.
    scenario_a_repeat = retriever.retrieve(
        query_features=query,
        product_model="TW-AA-PROTOTYPE-V1",
        top3_root_causes=TOP3,
        top_k=3,
        process_context=process_context_from_payload(
            fixture_payload["contexts"]["scenario_a"]
        ),
    )
    plan_a_repeat = planner.generate(retrieval=scenario_a_repeat, **planning_args)
    assert scenario_a == scenario_a_repeat
    assert plan_a == plan_a_repeat
    assert contexts["scenario_a"].context_hash == scenario_a_repeat.context_hash


def test_context_supplied_with_only_legacy_cases_cannot_drive_case_guidance(tmp_path) -> None:
    assets = _assets(tmp_path)
    _payload, contexts, _profiles = _load_process_fixture()
    by_id = {case.case_id: case for case in assets.cases}
    retriever = ProcessAwareCaseRetriever(assets, ())
    decision = retriever.retrieve(
        query_features=_query(by_id["tw-aa-approved-011"]),
        product_model="TW-AA-PROTOTYPE-V1",
        top3_root_causes=TOP3,
        top_k=3,
        process_context=contexts["scenario_a"],
    )
    assert isinstance(decision, ProcessAwareCaseRetrievalDecision)
    assert decision.eligible_case_ids == ()
    assert decision.guidance_reason_code == "CONTEXT_INSUFFICIENT"
    assert decision.informational_cases

    planner = ProcessAwareParameterPlanGenerator()
    plan = planner.generate(
        retrieval=decision,
        root_cause="PLANE_TILT",
        parameter_family="PITCH_ROLL",
        current_values=_values(),
        direction_evidence=(_evidence("pitch", 5),),
        snapshot=_snapshot(),
        diagnostic_result_version="tw-diagnostic-result-v1",
        cases=tuple(_historical(case) for case in assets.cases),
        feature_definition_version=FEATURE_DEFINITION_VERSION,
        product_model="TW-AA-PROTOTYPE-V1",
    )
    assert plan.case_guidance_status == "CONTEXT_INSUFFICIENT"
    assert plan.case_guidance_reason_code == "CONTEXT_INSUFFICIENT"
    assert all(item.generation_type != "CASE_GUIDED" for item in plan.ordered_candidates)
    assert [item.generation_type for item in plan.ordered_candidates] == [
        "CONSERVATIVE",
        "STANDARD",
    ]


def test_none_context_is_exact_legacy_v1_decision_and_fixed_demo_regression(tmp_path) -> None:
    assets = _assets(tmp_path)
    _payload, _contexts, profiles = _load_process_fixture()
    query = _query(next(case for case in assets.cases if case.case_id == "tw-aa-approved-011"))
    legacy = StructuredCaseRetriever(assets).retrieve(
        query_features=query,
        product_model="TW-AA-PROTOTYPE-V1",
        top3_root_causes=TOP3,
        top_k=3,
    )
    dispatched = ProcessAwareCaseRetriever(assets, profiles).retrieve(
        query_features=query,
        product_model="TW-AA-PROTOTYPE-V1",
        top3_root_causes=TOP3,
        top_k=3,
        process_context=None,
    )
    assert dispatched == legacy
    assert not isinstance(dispatched, ProcessAwareCaseRetrievalDecision)

    client, app = make_planning_client(tmp_path / "fixed-demo")
    with client:
        task, diagnostic, retrieval = _prepare(client)
        response = client.post(
            f"/api/tasks/{task['task_id']}/parameter-plans",
            json={
                "diagnostic_result_id": diagnostic["diagnostic_result_id"],
                "case_retrieval_result_id": retrieval["retrieval_result_id"],
            },
        )
    assert response.status_code == 200
    planning = response.json()["planning"]
    selected = planning["ordered_candidates"][0]
    assert task["task_id"] == "tw-demo-task-001"
    assert diagnostic["ordered_top3"][0]["root_cause"] == "PLANE_TILT"
    assert diagnostic["diagnostic_result_id"] == "tw-diagnostic-8edf69edfa99e4ae"
    assert diagnostic["result_hash"] == "8edf69edfa99e4aebea96a90f830d4930d98d23b315f5f21442ecc02753da99e"
    assert [case["case_id"] for case in retrieval["ordered_cases"]] == [
        "tw-aa-approved-011",
        "tw-aa-approved-001",
        "tw-aa-approved-002",
    ]
    assert retrieval["retrieval_result_version"] == "tw-case-retrieval-result-v1"
    assert retrieval["retrieval_result_id"] == "tw-case-retrieval-545f32f8430fd84a"
    assert retrieval["result_hash"] == "545f32f8430fd84a2d34488fc417e3d8d864a3e027cff62258d572b10e597358"
    assert planning["planning_result_id"] == "tw-parameter-planning-b590581b869393f7"
    assert planning["result_hash"] == "b678d63e08cf565c4e3dc9336acf2d678c85faf9d7e6beac191f7eb1bcb01d52"
    assert selected["candidate_id"] == "tw-parameter-candidate-2b7c09c86136ee11"
    assert selected["candidate_hash"] == "2b7c09c86136ee117229d8cfdf66494bcc976af9a1d31afd6c71b22430ed97a2"
    assert selected["generation_type"] == "CONSERVATIVE"
    assert selected["current_values"]["pitch"] == "0.250000"
    assert selected["proposed_values"]["pitch"] == "0.200000"
    assert selected["delta_ticks"] == {"pitch": -1}
    assert app.state.boundary_counters == {
        "simulator_gateway_assemblies": 0,
        "simulator_gateway_calls": 0,
        "llm_calls": 0,
        "external_network_requests": 0,
    }
