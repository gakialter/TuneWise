from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest

from tools.generate_diagnostic_assets import build_partition, generate
from tunewise.diagnosis import (
    DiagnosticAssetLoader,
    DiagnosticGuardError,
    RootCauseDiagnoser,
    record_diagnosis,
)
from tunewise.detection import ControlLimitRegistry


def load_assets(tmp_path):
    root = tmp_path / "diagnostic"
    generate(root, seed=20260718)
    manifest_hash = hashlib.sha256((root / "manifest.json").read_bytes()).hexdigest()
    return DiagnosticAssetLoader(root, manifest_hash).load()


def test_real_scaler_and_logistic_regression_rank_plane_tilt_with_structured_explanation(tmp_path):
    assets = load_assets(tmp_path)
    rows, _labels = build_partition(20260718, "REPRESENTATIVE", 1)

    result = RootCauseDiagnoser(assets).diagnose_values(
        rows[0],
        ControlLimitRegistry.snapshot_for("tw-rules-v1"),
    )

    assert result.ordered_top3[0].root_cause == "PLANE_TILT"
    assert len(result.ordered_top3) == 3
    assert result.ordered_top3[0].adjustability == "ADJUSTABLE"
    assert 0 < float(result.ordered_top3[0].normalized_score) <= 1
    assert len(result.ordered_top3[0].positive_logit_contributions) in range(3, 6)
    contribution = result.ordered_top3[0].positive_logit_contributions[0]
    assert contribution.description == "该特征对当前类别 logit 的贡献"
    assert float(contribution.contribution) == round(
        float(contribution.standardized_feature_value) * float(contribution.class_coefficient),
        6,
    )
    assert result.model_version == "tw-model-v1"
    assert result.preprocessing_version == "tw-preprocessing-v1"
    assert result.feature_definition_version == "tw-feature-definition-v1"
    assert all(
        len(candidate.positive_logit_contributions) in range(3, 6)
        for candidate in result.ordered_top3
    )


@pytest.mark.parametrize(
    ("row_index", "expected_root_cause", "adjustability"),
    [
        (0, "PLANE_TILT", "ADJUSTABLE"),
        (1, "XY_DECENTER", "ADJUSTABLE"),
        (2, "PLATFORM_INSTABILITY", "INSPECTION_ONLY"),
        (3, "REFERENCE_DRIFT", "INSPECTION_ONLY"),
        (4, "Z_DEFOCUS_CONDITIONAL", "ADJUSTABLE"),
    ],
)
def test_five_representative_observable_fixtures_use_the_frozen_class_order(
    tmp_path,
    row_index,
    expected_root_cause,
    adjustability,
):
    assets = load_assets(tmp_path)
    rows, _labels = build_partition(20260718, "REPRESENTATIVE", 1)

    result = RootCauseDiagnoser(assets).diagnose_values(
        rows[row_index],
        ControlLimitRegistry.snapshot_for("tw-rules-v1"),
    )

    assert result.ordered_top3[0].root_cause == expected_root_cause
    assert result.ordered_top3[0].adjustability == adjustability
    assert result.evidence_status == "SUFFICIENT_EVIDENCE"


def test_z_gate_passes_for_global_symmetric_drop_and_fails_for_asymmetry(tmp_path):
    assets = load_assets(tmp_path)
    rows, _labels = build_partition(20260718, "REPRESENTATIVE", 1)
    diagnoser = RootCauseDiagnoser(assets)

    z_result = diagnoser.diagnose_values(
        rows[4], ControlLimitRegistry.snapshot_for("tw-rules-v1")
    )
    asymmetric_result = diagnoser.diagnose_values(
        rows[0], ControlLimitRegistry.snapshot_for("tw-rules-v1")
    )

    assert z_result.z_gate_result.passed is True
    assert z_result.z_gate_result.status == "PASSED"
    assert all(check.status == "PASSED" for check in z_result.z_gate_result.checks)
    assert asymmetric_result.z_gate_result.passed is False
    assert asymmetric_result.z_gate_result.removed_category == "Z_DEFOCUS_CONDITIONAL"
    assert "Z_DEFOCUS_CONDITIONAL" not in {
        candidate.root_cause for candidate in asymmetric_result.ordered_top3
    }
    assert next(
        check for check in asymmetric_result.evidence_checks
        if check.rule_id == "Z_GATE_CONSISTENCY"
    ).status == "PASSED"


def test_z_removal_renormalizes_without_changing_other_tie_order(tmp_path):
    assets = load_assets(tmp_path)
    rows, _labels = build_partition(20260718, "REPRESENTATIVE", 1)
    standardized = [
        (value - float(assets.preprocessing["mean"][index]))
        / float(assets.preprocessing["scale"][index])
        for index, value in enumerate(rows[0])
    ]
    shared_coefficient = [
        1.0 if value > 0 else -1.0 if value < 0 else 0.0
        for value in standardized
    ]
    tied_model = {
        **assets.model,
        "coefficient": [shared_coefficient for _ in range(5)],
        "intercept": [0.0] * 5,
    }

    result = RootCauseDiagnoser(replace(assets, model=tied_model)).diagnose_values(
        rows[0], ControlLimitRegistry.snapshot_for("tw-rules-v1")
    )

    assert [candidate.root_cause for candidate in result.ordered_top3] == [
        "PLANE_TILT",
        "XY_DECENTER",
        "PLATFORM_INSTABILITY",
    ]
    assert [candidate.normalized_score for candidate in result.ordered_top3] == [
        "0.250000",
        "0.250000",
        "0.250000",
    ]
    assert result.evidence_status == "INSUFFICIENT_EVIDENCE"
    assert result.parameter_candidate_count == 0
    assert [check.status for check in result.evidence_checks[:2]] == ["FAILED", "FAILED"]


def test_candidate_without_three_positive_contributions_is_structurally_rejected(tmp_path):
    assets = load_assets(tmp_path)
    rows, _labels = build_partition(20260718, "REPRESENTATIVE", 1)
    no_contribution_model = {
        **assets.model,
        "coefficient": [[0.0] * 50 for _ in range(5)],
        "intercept": [0.0] * 5,
    }

    with pytest.raises(DiagnosticGuardError) as error:
        RootCauseDiagnoser(replace(assets, model=no_contribution_model)).diagnose_values(
            rows[0], ControlLimitRegistry.snapshot_for("tw-rules-v1")
        )

    assert error.value.code == "DIAGNOSTIC_EXPLANATION_INSUFFICIENT"


def test_model_rule_conflict_is_visible_and_forces_insufficient_evidence(tmp_path):
    assets = load_assets(tmp_path)
    rows, _labels = build_partition(20260718, "REPRESENTATIVE", 1)
    plane = list(rows[0])
    for name in (
        "left_right_difference",
        "top_bottom_difference",
        "diagonal_difference",
        "corner_mtf_range",
        "corner_mtf_std",
    ):
        plane[assets.model["feature_names"].index(name)] = 0.0

    result = RootCauseDiagnoser(assets).diagnose_values(
        plane, ControlLimitRegistry.snapshot_for("tw-rules-v1")
    )

    assert result.ordered_top3[0].root_cause == "PLANE_TILT"
    assert result.ordered_top3[0].conflict_evidence[0].rule_id == "PLANE_TILT_SPATIAL_PATTERN"
    assert result.evidence_status == "INSUFFICIENT_EVIDENCE"


def test_positive_contributions_use_stable_fixed_precision_order(tmp_path):
    assets = load_assets(tmp_path)
    rows, _labels = build_partition(20260718, "REPRESENTATIVE", 1)

    result = RootCauseDiagnoser(assets).diagnose_values(
        rows[0], ControlLimitRegistry.snapshot_for("tw-rules-v1")
    )
    contributions = result.ordered_top3[0].positive_logit_contributions

    assert list(contributions) == sorted(
        contributions,
        key=lambda item: (-round(float(item.contribution), 6), item.feature_index),
    )


def test_business_result_hash_excludes_created_at_and_derived_record_id(tmp_path):
    assets = load_assets(tmp_path)
    rows, _labels = build_partition(20260718, "REPRESENTATIVE", 1)
    decision = RootCauseDiagnoser(assets).diagnose_values(
        rows[0], ControlLimitRegistry.snapshot_for("tw-rules-v1")
    )
    common = {
        "task_id": "task-a",
        "detection_result_id": "detection-a",
        "input_data_version": "tw-dataset-v1",
        "input_feature_hash": "a" * 64,
        "anomaly_result": "TARGET_ANOMALY",
    }

    first = record_diagnosis(decision, created_at="2026-01-01T00:00:00Z", **common)
    second = record_diagnosis(decision, created_at="2030-01-01T00:00:00Z", **common)

    assert first.created_at != second.created_at
    assert first.result_hash == second.result_hash
    assert first.diagnostic_result_id == second.diagnostic_result_id
    assert first.ordered_top3 == decision.ordered_top3
    assert first.evidence_checks == decision.evidence_checks
    assert first.z_gate_result == decision.z_gate_result
    assert first.diagnostic_result_version == "tw-diagnostic-result-v1"
