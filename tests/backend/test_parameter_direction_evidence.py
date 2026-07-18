from __future__ import annotations

from dataclasses import replace

import pytest

from tunewise.parameter_planning import (
    DirectionEvidenceGenerator,
    DirectionRuleSet,
    ParameterConstraintSnapshot,
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


def _rules() -> DirectionRuleSet:
    return DirectionRuleSet.from_payload(
        {
            "direction_rule_version": "tw-direction-rules-v1",
            "rule_set_version": "tw-rules-v1",
            "minimum_spatial_support": "0.040000",
            "axis_rules": {
                "pitch": {
                    "root_cause": "PLANE_TILT",
                    "feature_name": "top_bottom_difference",
                    "sign_relation": "SAME_SIGN",
                    "rule_id": "PLANE_TILT_PITCH_SAME_SIGN",
                },
                "roll": {
                    "root_cause": "PLANE_TILT",
                    "feature_name": "left_right_difference",
                    "sign_relation": "OPPOSITE_SIGN",
                    "rule_id": "PLANE_TILT_ROLL_OPPOSITE_SIGN",
                },
                "x_offset": {
                    "root_cause": "XY_DECENTER",
                    "feature_name": "left_right_difference",
                    "sign_relation": "SAME_SIGN",
                    "rule_id": "XY_DECENTER_X_SAME_SIGN",
                },
                "y_offset": {
                    "root_cause": "XY_DECENTER",
                    "feature_name": "top_bottom_difference",
                    "sign_relation": "OPPOSITE_SIGN",
                    "rule_id": "XY_DECENTER_Y_OPPOSITE_SIGN",
                },
            },
            "z_rule": {
                "root_cause": "Z_DEFOCUS_CONDITIONAL",
                "rule_id": "Z_DEFOCUS_GATE_AND_GLOBAL_PATTERN",
                "supporting_features": ["mtf_center_mean", "corner_mtf_mean"],
            },
        }
    )


def _generate(
    root_cause: str,
    *,
    current_values: dict[str, str],
    features: dict[str, str],
    z_gate_passed: bool = False,
    snapshot: ParameterConstraintSnapshot | None = None,
):
    return DirectionEvidenceGenerator(_rules()).generate(
        root_cause=root_cause,
        current_values=current_values,
        features=features,
        snapshot=snapshot or _snapshot(),
        diagnostic_result_version="tw-diagnostic-result-v1",
        feature_definition_version="tw-feature-definition-v1",
        z_gate_passed=z_gate_passed,
    )


@pytest.mark.parametrize(
    ("parameter_name", "current_values", "features", "expected_direction"),
    [
        ("pitch", {"pitch": "0.250000", "roll": "0.000000"}, {"top_bottom_difference": "0.130000", "left_right_difference": "0.010000"}, "DECREASE"),
        ("roll", {"pitch": "0.000000", "roll": "-0.200000"}, {"top_bottom_difference": "0.010000", "left_right_difference": "0.120000"}, "INCREASE"),
        ("x_offset", {"x_offset": "0.150000", "y_offset": "0.000000"}, {"left_right_difference": "0.110000", "top_bottom_difference": "0.010000"}, "DECREASE"),
        ("y_offset", {"x_offset": "0.000000", "y_offset": "-0.150000"}, {"left_right_difference": "0.010000", "top_bottom_difference": "0.110000"}, "INCREASE"),
    ],
)
def test_direction_evidence_requires_axis_specific_spatial_support(
    parameter_name: str,
    current_values: dict[str, str],
    features: dict[str, str],
    expected_direction: str,
) -> None:
    root_cause = "PLANE_TILT" if parameter_name in {"pitch", "roll"} else "XY_DECENTER"
    decision = _generate(root_cause, current_values=current_values, features=features)

    usable = [item for item in decision.direction_evidence if item.conflict_status == "NO_CONFLICT"]
    assert [item.parameter_name for item in usable] == [parameter_name]
    assert usable[0].recommended_direction == expected_direction
    assert usable[0].current_tick in {-4, -3, 3, 5}
    assert usable[0].evidence_hash


def test_two_supported_plane_tilt_axes_produce_two_independent_evidence_records() -> None:
    decision = _generate(
        "PLANE_TILT",
        current_values={"pitch": "0.250000", "roll": "-0.200000"},
        features={"top_bottom_difference": "0.130000", "left_right_difference": "0.120000"},
    )

    assert [item.parameter_name for item in decision.usable_evidence] == ["pitch", "roll"]


def test_parameter_at_nominal_does_not_produce_adjustable_direction_evidence() -> None:
    decision = _generate(
        "PLANE_TILT",
        current_values={"pitch": "0.000000", "roll": "-0.200000"},
        features={"top_bottom_difference": "0.130000", "left_right_difference": "0.120000"},
    )

    assert [item.parameter_name for item in decision.usable_evidence] == ["roll"]


def test_spatial_pattern_conflicting_with_parameter_deviation_is_not_usable() -> None:
    decision = _generate(
        "PLANE_TILT",
        current_values={"pitch": "0.250000", "roll": "0.000000"},
        features={"top_bottom_difference": "-0.130000", "left_right_difference": "0.010000"},
    )

    assert decision.usable_evidence == ()
    assert decision.direction_evidence[0].conflict_status == "CONFLICT"
    assert decision.direction_evidence[0].conflicting_features


def test_z_direction_requires_existing_z_gate_and_moves_toward_snapshot_nominal() -> None:
    passed = _generate(
        "Z_DEFOCUS_CONDITIONAL",
        current_values={"z_offset": "0.150000"},
        features={"mtf_center_mean": "0.700000", "corner_mtf_mean": "0.580000"},
        z_gate_passed=True,
    )
    refused = _generate(
        "Z_DEFOCUS_CONDITIONAL",
        current_values={"z_offset": "0.150000"},
        features={"mtf_center_mean": "0.700000", "corner_mtf_mean": "0.580000"},
        z_gate_passed=False,
    )

    assert passed.usable_evidence[0].recommended_direction == "DECREASE"
    assert refused.usable_evidence == ()
    assert refused.refusal_code == "Z_GATE_NOT_PASSED"


def test_direction_and_ticks_use_task_snapshot_nominal_instead_of_zero() -> None:
    base = _snapshot()
    snapshot = replace(
        base,
        constraints=tuple(
            replace(item, nominal_value="0.100000")
            if item.parameter_name == "pitch"
            else item
            for item in base.constraints
        ),
    )

    decision = _generate(
        "PLANE_TILT",
        current_values={"pitch": "0.250000", "roll": "0.000000"},
        features={"top_bottom_difference": "0.130000", "left_right_difference": "0.010000"},
        snapshot=snapshot,
    )

    assert decision.usable_evidence[0].nominal_value == "0.100000"
    assert decision.usable_evidence[0].current_tick == 3
    assert decision.usable_evidence[0].recommended_direction == "DECREASE"
