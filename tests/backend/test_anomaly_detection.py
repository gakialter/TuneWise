from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from tunewise.detection import (
    AnomalyDetector,
    AnomalyResult,
    ControlLimitSnapshot,
    DetectionInput,
    RuleCheckStatus,
    SpcRuleSnapshot,
)


CONTROL_LIMITS = ControlLimitSnapshot(
    snapshot_version="tw-control-limits-test-v1",
    rule_set_version="tw-rules-test-v1",
    center_lower_limit=Decimal("0.720000"),
    corner_lower_limit=Decimal("0.620000"),
    asymmetry_limit=Decimal("0.120000"),
    corner_std_limit=Decimal("0.050000"),
)

SPC_RULES = SpcRuleSnapshot(
    snapshot_version="tw-spc-detection-test-v1",
    rule_set_version="tw-rules-test-v1",
    minimum_sample_count=8,
    minimum_consecutive_violations=3,
    minimum_violation_ratio=Decimal("0.250000"),
    center_clear_degradation_margin=Decimal("0.020000"),
    global_corner_fraction=Decimal("0.750000"),
)


def measurement(
    sample_index: int,
    *,
    center: str = "0.800000",
    corners: tuple[str, str, str, str] = (
        "0.700000",
        "0.700000",
        "0.700000",
        "0.700000",
    ),
) -> dict[str, str]:
    return {
        "sample_index": str(sample_index),
        "timestamp": f"2026-07-18T00:00:{sample_index:02d}.000000Z",
        "x_offset": "0.000000",
        "y_offset": "0.000000",
        "pitch": "0.000000",
        "roll": "0.000000",
        "z_offset": "0.000000",
        "vibration_rms": "0.010000",
        "repeat_position_error": "0.010000",
        "calibration_residual_x": "0.000000",
        "calibration_residual_y": "0.000000",
        "mtf_center": center,
        "mtf_lt": corners[0],
        "mtf_rt": corners[1],
        "mtf_lb": corners[2],
        "mtf_rb": corners[3],
    }


def detection_input(
    rows: list[dict[str, str]],
    *,
    rules: SpcRuleSnapshot = SPC_RULES,
) -> DetectionInput:
    return DetectionInput(
        task_id="tw-test-task-001",
        batch_id="tw-test-batch-001",
        measurements=tuple(rows),
        control_limits=CONTROL_LIMITS,
        rule_snapshot=rules,
        input_data_version="tw-dataset-test-v1",
        input_hash="1" * 64,
    )


def run(rows: list[dict[str, str]], *, rules: SpcRuleSnapshot = SPC_RULES):
    return AnomalyDetector().detect(detection_input(rows, rules=rules))


def target_rows(count: int = 8) -> list[dict[str, str]]:
    return [
        measurement(
            index,
            corners=("0.710000", "0.750000", "0.635000", "0.565000"),
        )
        for index in range(count)
    ]


def test_center_qualified_persistent_corner_asymmetry_is_target_anomaly():
    result = run(target_rows())

    assert result.anomaly_result is AnomalyResult.TARGET_ANOMALY
    assert result.aggregate_metrics.mtf_center == "0.800000"
    assert result.aggregate_metrics.corner_mtf_min == "0.565000"
    assert result.persistence_evidence.violating_sample_count == 8
    assert result.persistence_evidence.maximum_consecutive_violations == 8


def test_center_does_not_need_to_be_near_its_lower_limit_for_target_anomaly():
    result = run(
        [
            measurement(
                index,
                center="0.900000",
                corners=("0.710000", "0.750000", "0.635000", "0.565000"),
            )
            for index in range(8)
        ]
    )

    assert result.anomaly_result is AnomalyResult.TARGET_ANOMALY


def test_normal_batch_stops_without_target_or_global_degradation():
    result = run([measurement(index) for index in range(8)])

    assert result.anomaly_result is AnomalyResult.NORMAL
    assert result.persistence_evidence.violating_sample_count == 0


def test_center_and_corners_degrading_together_route_to_global_protection():
    result = run(
        [
            measurement(
                index,
                center="0.680000",
                corners=("0.580000", "0.590000", "0.575000", "0.585000"),
            )
            for index in range(8)
        ]
    )

    assert result.anomaly_result is AnomalyResult.NON_TARGET_GLOBAL_DEGRADATION
    assert result.rule_checks[1].rule_id == "GLOBAL_DEGRADATION_PROTECTION"
    assert result.rule_checks[1].status is RuleCheckStatus.PASSED
    assert result.persistence_evidence.violating_sample_count == 8
    assert result.persistence_evidence.maximum_consecutive_violations == 8
    assert result.persistence_evidence.violation_ratio == "1.000000"


def test_too_few_samples_route_to_insufficient_data_without_default_filling():
    result = run(target_rows(7))

    assert result.anomaly_result is AnomalyResult.INSUFFICIENT_DATA
    assert result.rule_checks[0].rule_id == "INPUT_DATA_SUFFICIENT"
    assert result.rule_checks[0].status is RuleCheckStatus.FAILED
    assert all(
        check.status is RuleCheckStatus.NOT_EVALUATED
        for check in result.rule_checks[1:]
    )


def test_missing_required_measurement_routes_to_insufficient_data():
    rows = target_rows()
    del rows[3]["mtf_rb"]

    result = run(rows)

    assert result.anomaly_result is AnomalyResult.INSUFFICIENT_DATA
    assert "mtf_rb" in result.rule_checks[0].detail


def test_blank_required_measurement_routes_to_insufficient_data():
    rows = target_rows()
    rows[2]["x_offset"] = ""

    result = run(rows)

    assert result.anomaly_result is AnomalyResult.INSUFFICIENT_DATA
    assert "x_offset" in result.rule_checks[0].detail


def test_one_isolated_corner_violation_does_not_trigger_target_anomaly():
    rows = [measurement(index) for index in range(8)]
    rows[3] = measurement(
        3,
        corners=("0.710000", "0.750000", "0.635000", "0.565000"),
    )

    result = run(rows)

    assert result.anomaly_result is AnomalyResult.NORMAL
    assert result.persistence_evidence.violating_sample_count == 1
    assert result.persistence_evidence.maximum_consecutive_violations == 1
    assert result.persistence_evidence.violation_ratio == "0.125000"
    minimum_check = next(
        check for check in result.rule_checks if check.rule_id == "CORNER_MIN_LIMIT"
    )
    assert minimum_check.actual == "0.565000"


def test_minimum_consecutive_boundary_is_inclusive():
    rules = replace(SPC_RULES, minimum_violation_ratio=Decimal("0.750000"))
    rows = [measurement(index) for index in range(8)]
    for index in (2, 3, 4):
        rows[index] = target_rows()[index]

    result = run(rows, rules=rules)

    assert result.anomaly_result is AnomalyResult.TARGET_ANOMALY
    assert result.persistence_evidence.maximum_consecutive_violations == 3
    assert result.persistence_evidence.consecutive_condition_met is True


def test_consecutive_count_below_boundary_does_not_trigger():
    rules = replace(SPC_RULES, minimum_violation_ratio=Decimal("0.750000"))
    rows = [measurement(index) for index in range(8)]
    for index in (2, 3):
        rows[index] = target_rows()[index]

    result = run(rows, rules=rules)

    assert result.anomaly_result is AnomalyResult.NORMAL
    assert result.persistence_evidence.maximum_consecutive_violations == 2


def test_minimum_sample_ratio_boundary_is_inclusive():
    rows = [measurement(index) for index in range(8)]
    for index in (1, 5):
        rows[index] = target_rows()[index]

    result = run(rows)

    assert result.anomaly_result is AnomalyResult.TARGET_ANOMALY
    assert result.persistence_evidence.maximum_consecutive_violations == 1
    assert result.persistence_evidence.violation_ratio == "0.250000"
    assert result.persistence_evidence.ratio_condition_met is True


def test_sample_ratio_below_boundary_does_not_trigger():
    rows = [measurement(index) for index in range(8)]
    rows[1] = target_rows()[1]

    result = run(rows)

    assert result.anomaly_result is AnomalyResult.NORMAL
    assert result.persistence_evidence.violation_ratio == "0.125000"


@pytest.mark.parametrize(
    ("corners", "passed_rule", "expected_actual"),
    [
        (
            ("0.700000", "0.700000", "0.700000", "0.610000"),
            "CORNER_MIN_LIMIT",
            "0.610000",
        ),
        (
            ("0.620000", "0.680000", "0.680000", "0.741000"),
            "CORNER_RANGE_LIMIT",
            "0.121000",
        ),
        (
            ("0.620000", "0.620000", "0.740000", "0.740000"),
            "CORNER_STD_LIMIT",
            "0.060000",
        ),
    ],
)
def test_each_corner_signal_can_independently_trigger_target(
    corners,
    passed_rule,
    expected_actual,
):
    result = run([measurement(index, corners=corners) for index in range(8)])

    checks = {check.rule_id: check for check in result.rule_checks}
    assert result.anomaly_result is AnomalyResult.TARGET_ANOMALY
    assert checks[passed_rule].status is RuleCheckStatus.PASSED
    assert checks[passed_rule].actual == expected_actual
    assert sum(
        checks[rule].status is RuleCheckStatus.PASSED
        for rule in ("CORNER_MIN_LIMIT", "CORNER_RANGE_LIMIT", "CORNER_STD_LIMIT")
    ) == 1


def test_clearly_low_center_with_prevalently_low_corners_takes_global_priority():
    rows = [
        measurement(
            index,
            center="0.690000",
            corners=("0.550000", "0.570000", "0.590000", "0.700000"),
        )
        for index in range(8)
    ]

    result = run(rows)

    assert result.anomaly_result is AnomalyResult.NON_TARGET_GLOBAL_DEGRADATION


def test_rule_checks_have_fixed_order_and_result_hash_is_deterministic():
    first = run(target_rows())
    second = run(target_rows())

    assert [check.rule_id for check in first.rule_checks] == [
        "INPUT_DATA_SUFFICIENT",
        "GLOBAL_DEGRADATION_PROTECTION",
        "CENTER_NOT_CLEARLY_LOW",
        "CORNER_MIN_LIMIT",
        "CORNER_RANGE_LIMIT",
        "CORNER_STD_LIMIT",
        "CORNER_SIGNAL_PRESENT",
        "MINIMUM_CONSECUTIVE_VIOLATIONS",
        "MINIMUM_VIOLATION_RATIO",
        "PERSISTENCE_CONDITION",
        "TARGET_ANOMALY_DECISION",
    ]
    assert first == second
    assert first.result_hash == second.result_hash
    assert len(first.result_hash) == 64
