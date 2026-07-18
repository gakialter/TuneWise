from __future__ import annotations

import math

import pytest

from tunewise.diagnostic_contract import FEATURE_NAMES
from tunewise.diagnosis import FeatureEngineeringError, FeatureEngineer


def measurement(index: int) -> dict[str, str]:
    return {
        "sample_index": str(index),
        "timestamp": f"2026-07-18T00:00:0{index}Z",
        "x_offset": f"{0.1 * index:.6f}",
        "y_offset": "-0.050000",
        "pitch": "0.250000",
        "roll": "-0.200000",
        "z_offset": "0.000000",
        "vibration_rms": f"{0.01 * (index + 1):.6f}",
        "repeat_position_error": "0.014000",
        "calibration_residual_x": "0.006000",
        "calibration_residual_y": "-0.004000",
        "mtf_center": "0.800000",
        "mtf_lt": f"{0.7 - 0.1 * index:.6f}",
        "mtf_rt": f"{0.5 + 0.1 * index:.6f}",
        "mtf_lb": "0.400000",
        "mtf_rb": "0.300000",
    }


def test_fixed_feature_order_aggregates_spatial_differences_and_trends():
    result = FeatureEngineer().derive(tuple(measurement(index) for index in range(3)))
    values = dict(zip(result.feature_names, result.values))

    assert result.feature_names == FEATURE_NAMES
    assert len(result.feature_names) == 50
    assert values["mtf_lt_mean"] == pytest.approx(0.6)
    assert values["mtf_lt_trend"] == pytest.approx(-0.1)
    assert values["mtf_rt_trend"] == pytest.approx(0.1)
    assert values["x_offset_mean"] == pytest.approx(0.1)
    assert values["x_offset_std"] == pytest.approx(math.sqrt(2 / 300))
    assert values["x_offset_trend"] == pytest.approx(0.1)
    assert values["vibration_rms_trend"] == pytest.approx(0.01)
    assert values["left_right_difference"] == pytest.approx(0.05)
    assert values["top_bottom_difference"] == pytest.approx(0.25)
    assert values["diagonal_difference"] == pytest.approx(-0.05)
    assert values["center_corner_gap"] == pytest.approx(0.325)
    assert len(result.input_feature_hash) == 64


def test_feature_contract_excludes_ids_partitions_labels_and_replay_fields():
    forbidden = {
        "batch_id",
        "task_id",
        "file_name",
        "partition",
        "random_seed",
        "root_cause",
        "primary_fault_truth",
        "scenario_ref",
        "replay_result",
    }

    assert forbidden.isdisjoint(FEATURE_NAMES)


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda row: row.pop("mtf_rb"), "DIAGNOSTIC_FEATURE_MISSING"),
        (lambda row: row.__setitem__("pitch", "NaN"), "DIAGNOSTIC_FEATURE_NON_FINITE"),
    ],
)
def test_missing_or_non_finite_observable_is_rejected_without_default_filling(mutate, code):
    rows = [measurement(index) for index in range(3)]
    mutate(rows[1])

    with pytest.raises(FeatureEngineeringError) as error:
        FeatureEngineer().derive(tuple(rows))

    assert error.value.code == code
