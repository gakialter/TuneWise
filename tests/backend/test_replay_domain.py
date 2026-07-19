from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from tools.generate_replay_assets import generate
from tunewise.replay import (
    BatchReplayMetrics,
    ReplayBoundaryAudit,
    ReplayEvaluator,
    ReplayEvaluationRuleSnapshot,
    ReplayGuardError,
    ReplayOrchestrator,
    ReplayResultCanonicalizer,
    create_replay_result,
    derive_replay_metrics,
)
from tunewise.detection import ControlLimitRegistry
from tunewise.simulator_gateway import LocalSimulatorGateway, SimulationRequest


def _rules() -> ReplayEvaluationRuleSnapshot:
    return ReplayEvaluationRuleSnapshot(
        snapshot_version="tw-evaluation-v1",
        evaluation_rule_version="tw-evaluation-v1",
        center_regression_tolerance="0.010000",
        minimum_corner_min_improvement="0.020000",
        minimum_range_reduction="0.020000",
        minimum_std_reduction="0.010000",
        center_lower_limit="0.720000",
        corner_lower_limit="0.620000",
        asymmetry_limit="0.120000",
    )


def _metrics(
    *,
    center: str = "0.830000",
    corner_min: str = "0.560000",
    corner_range: str = "0.180000",
    corner_std: str = "0.070000",
    control_limit_pass: bool = False,
    target_anomaly_triggered: bool = True,
) -> BatchReplayMetrics:
    return BatchReplayMetrics(
        sample_count=24,
        mtf_center_mean=center,
        mtf_center_std="0.002000",
        mtf_lt_mean="0.710000",
        mtf_rt_mean="0.750000",
        mtf_lb_mean="0.630000",
        mtf_rb_mean=corner_min,
        corner_mtf_mean="0.662500",
        corner_mtf_min=corner_min,
        corner_mtf_range=corner_range,
        corner_mtf_std=corner_std,
        center_corner_gap="0.167500",
        control_limit_pass=control_limit_pass,
        target_anomaly_triggered=target_anomaly_triggered,
        parameter_summary={
            "x_offset": "0.100000",
            "y_offset": "-0.050000",
            "pitch": "0.250000",
            "roll": "-0.200000",
            "z_offset": "0.000000",
        },
        metric_definition_version="tw-replay-metrics-v1",
        standard_deviation_method="POPULATION",
    )


def _gateway_runs(tmp_path: Path):
    root = tmp_path / "assets"
    manifest = generate(root)
    gateway = LocalSimulatorGateway(root, manifest["canonical_manifest_hash"])
    common = dict(
        scenario_ref="scn_c9b8a8d6bd33f72e893f33da85dfeb8e",
        scenario_ref_hash=manifest["scenario_ref_hash"],
        simulator_version=manifest["simulator_version"],
        replay_scenario_schema_version=manifest["replay_scenario_schema_version"],
        scenario_mapping_version=manifest["scenario_mapping_version"],
        sample_count=24,
        seed=manifest["fixed_seed"],
        disturbance_sequence_hash=manifest["disturbance_sequence_hash"],
    )
    before = gateway.run(
        SimulationRequest(
            **common,
            parameters={
                "x_offset": "0.100000",
                "y_offset": "-0.050000",
                "pitch": "0.250000",
                "roll": "-0.200000",
                "z_offset": "0.000000",
            },
        )
    )
    after = gateway.run(
        SimulationRequest(
            **common,
            parameters={
                "x_offset": "0.100000",
                "y_offset": "-0.050000",
                "pitch": "0.200000",
                "roll": "-0.200000",
                "z_offset": "0.000000",
            },
        )
    )
    return before, after


def test_demo_pair_uses_frozen_population_metrics_and_evaluates_success(tmp_path: Path) -> None:
    before_run, after_run = _gateway_runs(tmp_path)

    limits = ControlLimitRegistry.snapshot_for("tw-rules-v1")
    before = derive_replay_metrics(before_run.measurements, limits)
    after = derive_replay_metrics(after_run.measurements, limits)
    evaluation = ReplayEvaluator().evaluate(before, after, _rules())

    assert before.mtf_center_mean == "0.831003"
    assert before.corner_mtf_min == "0.567683"
    assert before.corner_mtf_range == "0.184837"
    assert before.corner_mtf_std == "0.071709"
    assert before.standard_deviation_method == "POPULATION"
    assert after.control_limit_pass is True
    assert after.corner_mtf_std <= "0.050000"
    assert after.target_anomaly_triggered is False
    assert evaluation.replay_status == "SUCCESS"
    assert tuple(check.check_id for check in evaluation.checks) == (
        "CENTER_REGRESSION_GUARD",
        "WORST_CORNER_REGRESSION_GUARD",
        "CORNER_RANGE_REGRESSION_GUARD",
        "CORNER_STD_REGRESSION_GUARD",
        "CONTROL_LIMIT_REGRESSION_GUARD",
        "WORST_CORNER_IMPROVEMENT",
        "CORNER_RANGE_REDUCTION",
        "CORNER_STD_REDUCTION",
        "CONTROL_LIMIT_PASS",
        "TARGET_ANOMALY_CLEARED",
    )


def test_evaluation_priority_is_regression_success_partial_then_no_improvement() -> None:
    before = _metrics()
    success = _metrics(
        center="0.829000",
        corner_min="0.625000",
        corner_range="0.110000",
        corner_std="0.045000",
        control_limit_pass=True,
        target_anomaly_triggered=False,
    )
    partial = _metrics(
        center="0.830000",
        corner_min="0.585000",
        corner_range="0.170000",
        corner_std="0.065000",
    )
    no_improvement = _metrics(
        center="0.830000",
        corner_min="0.565000",
        corner_range="0.175000",
        corner_std="0.066000",
    )
    center_regression_despite_corner_improvement = replace(
        success,
        mtf_center_mean="0.810000",
    )
    anomaly_gate_cleared_only_by_center_drop = replace(
        before,
        mtf_center_mean="0.821000",
        target_anomaly_triggered=False,
    )

    evaluator = ReplayEvaluator()

    assert evaluator.evaluate(before, center_regression_despite_corner_improvement, _rules()).replay_status == "REGRESSION"
    assert evaluator.evaluate(before, success, _rules()).replay_status == "SUCCESS"
    assert evaluator.evaluate(before, partial, _rules()).replay_status == "PARTIAL_IMPROVEMENT"
    assert evaluator.evaluate(before, no_improvement, _rules()).replay_status == "NO_IMPROVEMENT"
    assert (
        evaluator.evaluate(before, anomaly_gate_cleared_only_by_center_drop, _rules()).replay_status
        == "NO_IMPROVEMENT"
    )


def test_result_hash_is_stable_and_excludes_identity_and_time() -> None:
    payload = {
        "confirmed_plan_hash": "a" * 64,
        "simulator_version": "tw-simulator-v1",
        "replay_status": "SUCCESS",
        "attempt_count": 1,
        "baseline_metrics": _metrics(),
        "intervention_metrics": _metrics(control_limit_pass=True),
        "evaluation_checks": ReplayEvaluator().evaluate(
            _metrics(),
            _metrics(
                corner_min="0.625000",
                corner_range="0.110000",
                corner_std="0.045000",
                control_limit_pass=True,
                target_anomaly_triggered=False,
            ),
            _rules(),
        ).checks,
        "created_at": "2026-07-18T00:00:00.000000Z",
        "completed_at": "2026-07-18T00:00:01.000000Z",
        "replay_result_id": "random-one",
    }
    other = {
        **payload,
        "created_at": "2030-01-01T00:00:00.000000Z",
        "completed_at": "2030-01-01T00:00:02.000000Z",
        "replay_result_id": "random-two",
    }

    canonicalizer = ReplayResultCanonicalizer()

    assert canonicalizer.sha256(payload) == canonicalizer.sha256(other)
    assert len(canonicalizer.sha256(payload)) == 64


@pytest.mark.parametrize(
    "changed_field",
    [
        "created_at",
        "completed_at",
        "replay_result_id",
        "disclaimer",
        "no_device_write_notice",
    ],
)
def test_result_hash_excluded_fields_are_not_serialized(changed_field: str) -> None:
    payload = {
        "confirmed_plan_hash": "a" * 64,
        "replay_status": "SUCCESS",
        "attempt_count": 1,
        changed_field: "unstable",
    }

    assert changed_field.encode("utf-8") not in ReplayResultCanonicalizer().canonicalize(payload)


def test_replay_metric_nested_mapping_is_immutable() -> None:
    metrics = _metrics()

    with pytest.raises(TypeError, match="ReplayResult mappings are immutable"):
        metrics.parameter_summary["pitch"] = "9.999999"  # type: ignore[index]


def test_complete_simulation_evaluation_and_result_hash_chain_is_identical_ten_times(
    tmp_path: Path,
) -> None:
    root = tmp_path / "assets"
    manifest = generate(root)
    audit = ReplayBoundaryAudit()
    orchestrator = ReplayOrchestrator(root, manifest["canonical_manifest_hash"], audit)
    current = {
        "x_offset": "0.100000",
        "y_offset": "-0.050000",
        "pitch": "0.250000",
        "roll": "-0.200000",
        "z_offset": "0.000000",
    }
    proposed = {**current, "pitch": "0.200000"}

    results = []
    for index in range(10):
        computation = orchestrator.execute_pair(
            scenario_ref="scn_c9b8a8d6bd33f72e893f33da85dfeb8e",
            scenario_ref_hash=manifest["scenario_ref_hash"],
            sample_count=24,
            seed=20260718,
            current_values=current,
            proposed_values=proposed,
            imported_baseline_canonical_hash=(
                "c74206387e06287d6c11ee8a4c6cc46cae867e6967f0c790f5dfe2f5ef940668"
            ),
            evaluation_rules=_rules(),
            control_limits=ControlLimitRegistry.snapshot_for("tw-rules-v1"),
        )
        results.append(
            create_replay_result(
                task_id="tw-determinism-task",
                confirmed_plan_id="tw-confirmed-determinism",
                confirmed_plan_hash="a" * 64,
                candidate_id="tw-candidate-determinism",
                candidate_hash="b" * 64,
                request_idempotency_key=f"request-{index}",
                attempt_count=1,
                dataset_version="tw-dataset-v1",
                schema_version="tw-schema-v1",
                generator_version="tw-generator-v1",
                rule_set_version="tw-rules-v1",
                model_version="tw-model-v1",
                computation=computation,
                evaluation_rule_version="tw-evaluation-v1",
                created_at=f"2026-07-19T00:00:{index:02d}.000000Z",
                completed_at=f"2026-07-19T00:00:{index:02d}.000000Z",
            )
        )

    first = results[0]
    assert all(result.result_hash == first.result_hash for result in results[1:])
    assert all(result.before_observation_hash == first.before_observation_hash for result in results[1:])
    assert all(result.after_observation_hash == first.after_observation_hash for result in results[1:])
    assert all(result.baseline_metrics == first.baseline_metrics for result in results[1:])
    assert all(result.intervention_metrics == first.intervention_metrics for result in results[1:])
    assert all(result.evaluation_checks == first.evaluation_checks for result in results[1:])
    assert all(result.replay_status == "SUCCESS" for result in results)
    assert audit.counters["baseline_runs"] == 10
    assert audit.counters["intervention_runs"] == 10


def test_orchestrator_rejects_import_seed_that_is_not_bound_to_simulator_assets(
    tmp_path: Path,
) -> None:
    root = tmp_path / "assets"
    manifest = generate(root)
    audit = ReplayBoundaryAudit()
    orchestrator = ReplayOrchestrator(root, manifest["canonical_manifest_hash"], audit)
    current = {
        "x_offset": "0.100000",
        "y_offset": "-0.050000",
        "pitch": "0.250000",
        "roll": "-0.200000",
        "z_offset": "0.000000",
    }

    with pytest.raises(ReplayGuardError) as captured:
        orchestrator.execute_pair(
            scenario_ref="scn_c9b8a8d6bd33f72e893f33da85dfeb8e",
            scenario_ref_hash=manifest["scenario_ref_hash"],
            sample_count=24,
            seed=1,
            current_values=current,
            proposed_values={**current, "pitch": "0.200000"},
            imported_baseline_canonical_hash=(
                "c74206387e06287d6c11ee8a4c6cc46cae867e6967f0c790f5dfe2f5ef940668"
            ),
            evaluation_rules=_rules(),
            control_limits=ControlLimitRegistry.snapshot_for("tw-rules-v1"),
        )

    assert getattr(captured.value, "code", None) == "SIMULATOR_INPUT_MISMATCH"
    assert audit.counters["simulator_gateway_calls"] == 0
