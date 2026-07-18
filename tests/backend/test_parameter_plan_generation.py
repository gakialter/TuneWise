from __future__ import annotations

from dataclasses import replace

from tunewise.parameter_planning import (
    HistoricalCaseAction,
    ParameterGenerationPolicy,
    ParameterConstraintSnapshot,
    ParameterDirectionEvidence,
    ParameterPlanGenerator,
    direction_evidence_hash,
    record_parameter_planning,
)


def _snapshot() -> ParameterConstraintSnapshot:
    constraints = {}
    for name in ("x_offset", "y_offset", "pitch", "roll", "z_offset"):
        constraints[name] = {
            "nominal_value": "0.000000",
            "minimum": "-1.000000",
            "maximum": "1.000000",
            "step": "0.050000",
            "maximum_single_plan_delta": "0.100000" if name == "z_offset" else "0.200000",
        }
    return ParameterConstraintSnapshot.from_payload(
        {
            "snapshot_version": "tw-parameter-constraints-v1",
            "product_model": "TW-AA-PROTOTYPE-V1",
            "rule_set_version": "tw-rules-v1",
            "constraints": constraints,
        }
    )


def _evidence(name: str, current_tick: int) -> ParameterDirectionEvidence:
    current = f"{current_tick * 0.05:.6f}"
    item = ParameterDirectionEvidence(
        parameter_name=name,
        current_value=current,
        current_tick=current_tick,
        nominal_value="0.000000",
        nominal_tick=0,
        recommended_direction="DECREASE" if current_tick > 0 else "INCREASE",
        supporting_features=("axis_feature=0.120000",),
        supporting_rules=("AXIS_RULE",),
        conflicting_features=(),
        conflict_status="NO_CONFLICT",
        diagnostic_result_version="tw-diagnostic-result-v1",
        feature_definition_version="tw-feature-definition-v1",
        direction_rule_version="tw-direction-rules-v1",
        evidence_hash="",
    )
    return replace(item, evidence_hash=direction_evidence_hash(item))


def _values(**overrides: str) -> dict[str, str]:
    return {
        "x_offset": "0.000000",
        "y_offset": "0.000000",
        "pitch": "0.250000",
        "roll": "0.000000",
        "z_offset": "0.000000",
        **overrides,
    }


def _case(
    case_id: str,
    delta_ticks: int,
    *,
    status: str = "APPROVED",
    source_partition: str = "TRAIN",
    simulated_status: str = "SUCCESS",
    center_within_tolerance: bool = True,
    parameter_name: str = "pitch",
) -> HistoricalCaseAction:
    return HistoricalCaseAction(
        case_id=case_id,
        status=status,
        source_partition=source_partition,
        source_partition_id="diagnostic-dev-train-v1",
        station_type="AA",
        product_model="TW-AA-PROTOTYPE-V1",
        reviewed_root_cause="PLANE_TILT",
        parameter_family="PITCH_ROLL",
        parameter_delta_ticks={parameter_name: delta_ticks},
        action_version="tw-approved-case-action-v1",
        historical_safety_status="PASSED",
        historical_safety_rule_version="tw-parameter-safety-v1",
        historical_simulated_result_status=simulated_status,
        center_within_tolerance=center_within_tolerance,
        feature_definition_version="tw-feature-definition-v1",
        rule_set_version="tw-rules-v1",
        retrieval_rule_version="tw-case-retrieval-rules-v1",
        case_schema_version="tw-approved-case-schema-v1",
    )


def _generate(*, current_values=None, evidence=None, cases=()):
    return ParameterPlanGenerator().generate(
        root_cause="PLANE_TILT",
        parameter_family="PITCH_ROLL",
        current_values=current_values or _values(),
        direction_evidence=evidence or (_evidence("pitch", 5),),
        snapshot=_snapshot(),
        diagnostic_result_version="tw-diagnostic-result-v1",
        case_retrieval_result_version="tw-case-retrieval-result-v1" if cases else None,
        cases=cases,
        feature_definition_version="tw-feature-definition-v1",
        product_model="TW-AA-PROTOTYPE-V1",
    )


def test_rule_candidates_move_one_and_two_ticks_toward_nominal() -> None:
    decision = _generate()

    assert [candidate.generation_type for candidate in decision.ordered_candidates] == [
        "CONSERVATIVE",
        "STANDARD",
    ]
    assert [candidate.delta_ticks["pitch"] for candidate in decision.ordered_candidates] == [-1, -2]


def test_generator_uses_injected_versioned_generation_policy() -> None:
    policy = ParameterGenerationPolicy.from_payload(
        {
            "planning_rule_version": "tw-parameter-planning-v1",
            "rule_set_version": "tw-rules-v1",
            "generation_ticks": {"CONSERVATIVE": 2, "STANDARD": 3},
            "maximum_candidate_count": 3,
            "sort_order": [
                "total_absolute_delta_ticks:ASC",
                "supporting_case_count:DESC",
                "candidate_id:ASC",
            ],
            "case_action_version": "tw-approved-case-action-v1",
        }
    )

    decision = ParameterPlanGenerator(planning_policy=policy).generate(
        root_cause="PLANE_TILT",
        parameter_family="PITCH_ROLL",
        current_values=_values(),
        direction_evidence=(_evidence("pitch", 5),),
        snapshot=_snapshot(),
        diagnostic_result_version="tw-diagnostic-result-v1",
        case_retrieval_result_version=None,
        cases=(),
        feature_definition_version="tw-feature-definition-v1",
        product_model="TW-AA-PROTOTYPE-V1",
    )

    assert [item.delta_ticks["pitch"] for item in decision.ordered_candidates] == [-2, -3]


def test_case_guided_even_half_tick_median_rounds_to_nearest_grid_tick() -> None:
    decision = _generate(cases=(_case("case-2", -2), _case("case-3", -3)))

    case_guided = next(
        item for item in decision.ordered_candidates if "CASE_GUIDED_MEDIAN" in item.generation_sources
    )
    assert case_guided.delta_ticks["pitch"] == -3
    assert all(candidate.validation_status == "PASSED" for candidate in decision.ordered_candidates)


def test_standard_candidate_never_moves_past_nominal() -> None:
    decision = _generate(
        current_values=_values(pitch="0.050000"),
        evidence=(_evidence("pitch", 1),),
    )

    assert len(decision.ordered_candidates) == 1
    assert decision.ordered_candidates[0].proposed_ticks["pitch"] == 0
    assert set(decision.ordered_candidates[0].generation_sources) == {
        "RULE_CONSERVATIVE",
        "RULE_STANDARD",
    }


def test_case_guided_uses_compatible_case_median_magnitude_and_current_direction() -> None:
    cases = (_case("case-1", -1), _case("case-2", -3), _case("case-3", -4))
    decision = _generate(cases=cases)

    case_candidate = next(
        candidate
        for candidate in decision.ordered_candidates
        if candidate.generation_type == "CASE_GUIDED"
    )
    assert case_candidate.delta_ticks["pitch"] == -3
    assert case_candidate.supporting_case_ids == ("case-1", "case-2", "case-3")
    assert decision.case_guidance_status == "COMPATIBLE_APPROVED_CASES_USED"


def test_case_direction_conflicts_and_ineligible_sources_are_filtered_without_blocking_rules() -> None:
    cases = (
        _case("wrong-direction", 3),
        _case("pending", -3, status="PENDING_REVIEW"),
        _case("test", -3, source_partition="TEST"),
        _case("failed", -3, simulated_status="REGRESSION"),
        _case("center-regression", -3, center_within_tolerance=False),
        _case("unsafe-history", -9),
    )
    decision = _generate(cases=cases)

    assert [candidate.generation_type for candidate in decision.ordered_candidates] == [
        "CONSERVATIVE",
        "STANDARD",
    ]
    assert decision.case_guidance_status == "NO_COMPATIBLE_APPROVED_CASE"


def test_case_guided_is_capped_by_current_deviation_and_maximum_delta() -> None:
    decision = _generate(cases=(_case("case-maximum", -4),))

    case_candidate = next(
        candidate
        for candidate in decision.ordered_candidates
        if "CASE_GUIDED_MEDIAN" in candidate.generation_sources
    )
    assert case_candidate.delta_ticks["pitch"] == -4


def test_identical_case_guided_and_rule_candidate_are_deduplicated_and_sources_merge() -> None:
    decision = _generate(cases=(_case("case-standard", -2),))

    assert len(decision.ordered_candidates) == 2
    standard = next(
        candidate for candidate in decision.ordered_candidates if candidate.delta_ticks["pitch"] == -2
    )
    assert standard.generation_type == "STANDARD"
    assert set(standard.generation_sources) == {"RULE_STANDARD", "CASE_GUIDED_MEDIAN"}
    assert standard.supporting_case_ids == ("case-standard",)


def test_candidates_have_stable_hash_id_and_fixed_sorting() -> None:
    first = _generate(cases=(_case("case-4", -4), _case("case-3", -3), _case("case-2", -2)))
    second = _generate(cases=tuple(reversed((_case("case-4", -4), _case("case-3", -3), _case("case-2", -2)))))

    assert first.ordered_candidates == second.ordered_candidates
    assert [candidate.total_absolute_delta_ticks for candidate in first.ordered_candidates] == sorted(
        candidate.total_absolute_delta_ticks for candidate in first.ordered_candidates
    )
    assert all(candidate.candidate_hash for candidate in first.ordered_candidates)
    assert all(candidate.candidate_id.startswith("tw-parameter-candidate-") for candidate in first.ordered_candidates)


def test_all_zero_candidates_are_removed() -> None:
    evidence = replace(_evidence("pitch", 5), current_value="0.000000", current_tick=0)
    decision = _generate(current_values=_values(pitch="0.000000"), evidence=(evidence,))

    assert decision.ordered_candidates == ()


def test_planning_business_hash_excludes_runtime_identity_and_time() -> None:
    def record(task_id: str, diagnostic_id: str, created_at: str):
        return record_parameter_planning(
            task_id=task_id,
            diagnostic_result_id=diagnostic_id,
            case_retrieval_result_id=f"retrieval-{task_id}",
            top1_root_cause="PLANE_TILT",
            direction_evidence=(),
            ordered_candidates=(),
            parameter_constraints=(),
            planning_status="PARAMETER_RECOMMENDATION_REFUSED",
            refusal_code="TEST_REFUSAL",
            refusal_message="same business result",
            supporting_evidence=(),
            recommended_inspection_actions=(),
            case_guidance_status="NO_COMPATIBLE_APPROVED_CASE",
            input_bindings={
                "task_id": task_id,
                "diagnostic_result_id": diagnostic_id,
                "case_retrieval_result_id": f"retrieval-{task_id}",
                "measurement_hash": "same-measurement",
            },
            constraint_snapshot_version="tw-parameter-constraints-v1",
            rule_set_version="tw-rules-v1",
            feature_definition_version="tw-feature-definition-v1",
            diagnostic_result_version="tw-diagnostic-result-v1",
            case_retrieval_result_version="tw-case-retrieval-result-v1",
            planning_asset_manifest_hash="a" * 64,
            created_at=created_at,
        )

    first = record("random-task-a", "random-diagnostic-a", "2026-01-01T00:00:00Z")
    second = record("random-task-b", "random-diagnostic-b", "2027-01-01T00:00:00Z")

    assert first.input_hash == second.input_hash
    assert first.result_hash == second.result_hash
    assert first.planning_result_id != second.planning_result_id
