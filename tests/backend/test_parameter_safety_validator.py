from __future__ import annotations

from dataclasses import replace

import pytest

from tunewise.parameter_planning import (
    ParameterConstraintSnapshot,
    ParameterDirectionEvidence,
    ParameterPlanCandidate,
    ParameterSafetyValidator,
    SafetyVersionContext,
    candidate_content_hash,
    direction_evidence_hash,
)


def _snapshot() -> ParameterConstraintSnapshot:
    constraints = {}
    for name in ("x_offset", "y_offset", "pitch", "roll", "z_offset"):
        constraints[name] = {
            "nominal_value": "0.000000",
            "minimum": "-1.000000",
            "maximum": "1.000000",
            "step": "0.050000",
            "maximum_single_plan_delta": (
                "0.100000" if name == "z_offset" else "0.200000"
            ),
        }
    return ParameterConstraintSnapshot.from_payload(
        {
            "snapshot_version": "tw-parameter-constraints-v1",
            "product_model": "TW-AA-PROTOTYPE-V1",
            "rule_set_version": "tw-rules-v1",
            "constraints": constraints,
        }
    )


def _direction(
    *,
    current_value: str = "0.200000",
    current_tick: int | None = 4,
    direction: str = "DECREASE",
    conflict_status: str = "NO_CONFLICT",
) -> ParameterDirectionEvidence:
    evidence = ParameterDirectionEvidence(
        parameter_name="pitch",
        current_value=current_value,
        current_tick=current_tick,
        nominal_value="0.000000",
        nominal_tick=0,
        recommended_direction=direction,
        supporting_features=("top_bottom_difference=-0.140000",),
        supporting_rules=("PLANE_TILT_PITCH_OPPOSITE_SIGN",),
        conflicting_features=(),
        conflict_status=conflict_status,
        diagnostic_result_version="tw-diagnostic-result-v1",
        feature_definition_version="tw-feature-definition-v1",
        direction_rule_version="tw-direction-rules-v1",
        evidence_hash="",
    )
    return replace(evidence, evidence_hash=direction_evidence_hash(evidence))


def _candidate(
    *,
    current_pitch: str = "0.200000",
    proposed_pitch: str = "0.150000",
    current_pitch_tick: int | None = 4,
    proposed_pitch_tick: int | None = 3,
    delta_tick: int | None = -1,
    direction: ParameterDirectionEvidence | None = None,
    root_cause: str = "PLANE_TILT",
    parameter_family: str = "PITCH_ROLL",
) -> ParameterPlanCandidate:
    current_values = {
        "x_offset": "0.000000",
        "y_offset": "0.000000",
        "pitch": current_pitch,
        "roll": "0.000000",
        "z_offset": "0.000000",
    }
    proposed_values = {**current_values, "pitch": proposed_pitch}
    current_ticks = {
        "x_offset": 0,
        "y_offset": 0,
        "pitch": current_pitch_tick,
        "roll": 0,
        "z_offset": 0,
    }
    proposed_ticks = {**current_ticks, "pitch": proposed_pitch_tick}
    candidate = ParameterPlanCandidate(
        candidate_id="tw-plan-test",
        generation_type="CONSERVATIVE",
        generation_sources=("RULE_CONSERVATIVE",),
        root_cause=root_cause,
        parameter_family=parameter_family,
        current_values=current_values,
        proposed_values=proposed_values,
        current_ticks=current_ticks,
        proposed_ticks=proposed_ticks,
        deltas={"pitch": "-0.050000"},
        delta_ticks={"pitch": delta_tick},
        total_absolute_delta_ticks=abs(delta_tick or 0),
        direction_evidence=(direction or _direction(current_value=current_pitch, current_tick=current_pitch_tick),),
        supporting_case_ids=(),
        supporting_case_count=0,
        constraint_snapshot_version="tw-parameter-constraints-v1",
        rule_set_version="tw-rules-v1",
        direction_rule_version="tw-direction-rules-v1",
        safety_rule_version="tw-parameter-safety-v1",
        diagnostic_result_version="tw-diagnostic-result-v1",
        case_retrieval_result_version=None,
        validation_checks=(),
        validation_status="REJECTED",
        rejection_reasons=(),
        candidate_hash="",
    )
    return replace(candidate, candidate_hash=candidate_content_hash(candidate))


def test_validator_rejects_off_grid_current_value_without_rounding() -> None:
    candidate = _candidate(
        current_pitch="0.075000",
        proposed_pitch="0.025000",
        current_pitch_tick=None,
        proposed_pitch_tick=None,
        delta_tick=None,
        direction=_direction(current_value="0.075000", current_tick=None),
    )
    result = ParameterSafetyValidator().validate(
        candidate,
        snapshot=_snapshot(),
        versions=SafetyVersionContext(
            constraint_snapshot_version="tw-parameter-constraints-v1",
            rule_set_version="tw-rules-v1",
            direction_rule_version="tw-direction-rules-v1",
            safety_rule_version="tw-parameter-safety-v1",
            diagnostic_result_version="tw-diagnostic-result-v1",
            case_retrieval_result_version=None,
        ),
    )

    assert result.validation_status == "REJECTED"
    assert "CURRENT_VALUE_OFF_GRID" in result.rejection_reasons
    assert result.validated_candidate_hash == candidate.candidate_hash
    assert next(
        check for check in result.validation_checks if check.check_code == "CURRENT_VALUE_GRID"
    ).status == "FAILED"


def test_validator_passes_a_tick_exact_nominal_reducing_candidate() -> None:
    result = ParameterSafetyValidator().validate(
        _candidate(), snapshot=_snapshot(), versions=_versions()
    )

    assert result.validation_status == "PASSED"
    assert result.rejection_reasons == ()
    assert all(check.status == "PASSED" for check in result.validation_checks)


def _versions() -> SafetyVersionContext:
    return SafetyVersionContext(
        constraint_snapshot_version="tw-parameter-constraints-v1",
        rule_set_version="tw-rules-v1",
        direction_rule_version="tw-direction-rules-v1",
        safety_rule_version="tw-parameter-safety-v1",
        diagnostic_result_version="tw-diagnostic-result-v1",
        case_retrieval_result_version=None,
    )


def _rehash(candidate: ParameterPlanCandidate) -> ParameterPlanCandidate:
    without_hash = replace(candidate, candidate_hash="")
    return replace(without_hash, candidate_hash=candidate_content_hash(without_hash))


def test_validator_rejects_inconsistent_unchanged_ticks_and_delta_fields() -> None:
    inconsistent_ticks = _rehash(
        replace(_candidate(), current_ticks={**_candidate().current_ticks, "roll": 9})
    )
    inconsistent_deltas = _rehash(
        replace(_candidate(), deltas={"pitch": "-0.100000"})
    )

    tick_result = ParameterSafetyValidator().validate(
        inconsistent_ticks, snapshot=_snapshot(), versions=_versions()
    )
    delta_result = ParameterSafetyValidator().validate(
        inconsistent_deltas, snapshot=_snapshot(), versions=_versions()
    )

    assert "CANDIDATE_TICK_MISMATCH" in tick_result.rejection_reasons
    assert "CANDIDATE_DELTA_MISMATCH" in delta_result.rejection_reasons


def test_validator_rejects_direction_evidence_that_does_not_bind_current_candidate() -> None:
    stale_evidence = replace(_direction(), current_value="0.150000")
    stale_evidence = replace(
        stale_evidence, evidence_hash=direction_evidence_hash(stale_evidence)
    )
    candidate = _rehash(replace(_candidate(), direction_evidence=(stale_evidence,)))

    result = ParameterSafetyValidator().validate(
        candidate, snapshot=_snapshot(), versions=_versions()
    )

    assert "DIRECTION_EVIDENCE_INVALID" in result.rejection_reasons


def _multi_parameter_candidate(names: tuple[str, ...]) -> ParameterPlanCandidate:
    base = _candidate()
    current_values = dict(base.current_values)
    proposed_values = dict(base.current_values)
    current_ticks = dict(base.current_ticks)
    proposed_ticks = dict(base.current_ticks)
    evidence = []
    for name in names:
        current_values[name] = "0.200000"
        proposed_values[name] = "0.150000"
        current_ticks[name] = 4
        proposed_ticks[name] = 3
        item = replace(_direction(), parameter_name=name)
        evidence.append(replace(item, evidence_hash=direction_evidence_hash(item)))
    return _rehash(
        replace(
            base,
            current_values=current_values,
            proposed_values=proposed_values,
            current_ticks=current_ticks,
            proposed_ticks=proposed_ticks,
            deltas={name: "-0.050000" for name in names},
            delta_ticks={name: -1 for name in names},
            total_absolute_delta_ticks=len(names),
            direction_evidence=tuple(evidence),
        )
    )


@pytest.mark.parametrize(
    ("candidate", "reason"),
    [
        (_rehash(replace(_candidate(), direction_evidence=())), "DIRECTION_EVIDENCE_MISSING"),
        (_multi_parameter_candidate(("x_offset", "pitch")), "MIXED_PARAMETER_FAMILY"),
        (_multi_parameter_candidate(("x_offset", "y_offset", "pitch")), "PARAMETER_COUNT_EXCEEDED"),
        (
            _rehash(
                replace(
                    _candidate(),
                    current_values={**_candidate().current_values, "pitch": "0.2000001"},
                )
            ),
            "PARAMETER_NUMERIC_INVALID",
        ),
        (
            _rehash(
                replace(
                    _candidate(),
                    proposed_values={**_candidate().proposed_values, "pitch": "0.1500001"},
                )
            ),
            "PARAMETER_NUMERIC_INVALID",
        ),
        (
            _rehash(
                replace(
                    _candidate(),
                    proposed_values=dict(_candidate().current_values),
                    proposed_ticks=dict(_candidate().current_ticks),
                    deltas={},
                    delta_ticks={},
                    total_absolute_delta_ticks=0,
                )
            ),
            "ZERO_DELTA_CANDIDATE",
        ),
        (replace(_candidate(), candidate_hash="tampered"), "CANDIDATE_HASH_MISMATCH"),
    ],
)
def test_validator_rejects_structural_and_integrity_boundary(
    candidate: ParameterPlanCandidate,
    reason: str,
) -> None:
    result = ParameterSafetyValidator().validate(
        candidate, snapshot=_snapshot(), versions=_versions()
    )

    assert result.validation_status == "REJECTED"
    assert reason in result.rejection_reasons


@pytest.mark.parametrize(
    ("candidate", "reason"),
    [
        (_candidate(current_pitch="1.050000", current_pitch_tick=21), "CURRENT_VALUE_OUT_OF_RANGE"),
        (_candidate(proposed_pitch="1.050000", proposed_pitch_tick=21, delta_tick=17), "PROPOSED_VALUE_OUT_OF_RANGE"),
        (_candidate(proposed_pitch="0.175000", proposed_pitch_tick=None, delta_tick=None), "PROPOSED_VALUE_OFF_GRID"),
        (_candidate(proposed_pitch="-0.050000", proposed_pitch_tick=-1, delta_tick=-5), "NOMINAL_VALUE_CROSSED"),
        (_candidate(proposed_pitch="0.250000", proposed_pitch_tick=5, delta_tick=1), "NOMINAL_DEVIATION_NOT_REDUCED"),
        (_candidate(proposed_pitch="-0.100000", proposed_pitch_tick=-2, delta_tick=-6), "MAXIMUM_SINGLE_PLAN_DELTA_EXCEEDED"),
        (_candidate(direction=_direction(conflict_status="CONFLICT")), "DIRECTION_EVIDENCE_CONFLICT"),
        (_candidate(root_cause="XY_DECENTER"), "PARAMETER_NOT_ALLOWED_FOR_TOP1"),
    ],
)
def test_validator_rejects_each_frozen_safety_boundary(
    candidate: ParameterPlanCandidate,
    reason: str,
) -> None:
    result = ParameterSafetyValidator().validate(
        candidate, snapshot=_snapshot(), versions=_versions()
    )

    assert result.validation_status == "REJECTED"
    assert reason in result.rejection_reasons
