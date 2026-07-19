from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import asdict
from pathlib import Path
from typing import Mapping, Sequence

from .detection import ControlLimitSnapshot
from .importing import OBSERVABLE_FIELDS, ObservableCanonicalizer, ObservationValidationError
from .replay_contracts import (
    NO_DEVICE_WRITE_NOTICE,
    REPLAY_DISCLAIMER,
    REPLAY_DISCLAIMER_VERSION,
    REPLAY_METRIC_DEFINITION_VERSION,
    REPLAY_RESULT_CANONICALIZER_VERSION,
    REPLAY_RESULT_VERSION,
    BatchReplayMetrics,
    EvaluationCheck,
    FrozenReplayDict,
    ReplayBoundaryAudit,
    ReplayComputation,
    ReplayEvaluation,
    ReplayEvaluationRuleSnapshot,
    ReplayGuardError,
    ReplayResult,
    ReplayStatus,
)
from .replay_evaluation import (
    PARAMETER_FIELDS,
    ReplayEvaluator,
    derive_replay_metrics,
    metric_deltas,
)
from .replay_result import (
    ReplayResultCanonicalizer,
    create_replay_result,
    deserialize_replay_result,
    replay_result_business_payload,
)
from .simulator_gateway import (
    LocalSimulatorGateway,
    SimulationRequest,
    SimulatorGatewayError,
    canonical_json_bytes,
)


def _canonical_observations(measurements: Sequence[Mapping[str, str]]) -> str:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(OBSERVABLE_FIELDS)
    for row in sorted(measurements, key=lambda item: int(item["sample_index"])):
        writer.writerow([row[field] for field in OBSERVABLE_FIELDS])
    try:
        return ObservableCanonicalizer().canonicalize_csv(
            stream.getvalue().encode("utf-8")
        ).sha256
    except ObservationValidationError as error:
        raise ReplayGuardError("SIMULATOR_OUTPUT_INVALID", "模拟器可观测输出无法规范化。") from error


class ReplayOrchestrator:
    def __init__(
        self,
        replay_asset_root: Path,
        expected_replay_manifest_hash: str,
        boundary_audit: ReplayBoundaryAudit,
    ) -> None:
        self._gateway = LocalSimulatorGateway(
            replay_asset_root,
            expected_replay_manifest_hash,
        )
        self._boundary_audit = boundary_audit
        self._boundary_audit.counters["simulator_gateway_assemblies"] += 1

    def execute_pair(
        self,
        *,
        scenario_ref: str,
        scenario_ref_hash: str,
        sample_count: int,
        seed: int,
        current_values: Mapping[str, str],
        proposed_values: Mapping[str, str],
        imported_baseline_canonical_hash: str,
        evaluation_rules: ReplayEvaluationRuleSnapshot,
        control_limits: ControlLimitSnapshot,
    ) -> ReplayComputation:
        try:
            assets = self._gateway.asset_binding()
        except SimulatorGatewayError as error:
            raise ReplayGuardError(error.code, error.message) from error
        if assets.scenario_ref_hash != scenario_ref_hash:
            raise ReplayGuardError(
                "SCENARIO_REFERENCE_HASH_MISMATCH",
                "场景引用与模拟器资产绑定不一致。",
            )
        if seed != assets.fixed_seed:
            raise ReplayGuardError(
                "SIMULATOR_INPUT_MISMATCH",
                "导入数据与模拟器固定 seed 绑定不一致。",
            )
        common = dict(
            scenario_ref=scenario_ref,
            scenario_ref_hash=scenario_ref_hash,
            simulator_version=assets.simulator_version,
            replay_scenario_schema_version=assets.replay_scenario_schema_version,
            scenario_mapping_version=assets.scenario_mapping_version,
            sample_count=sample_count,
            seed=seed,
            disturbance_sequence_hash=assets.disturbance_sequence_hash,
        )
        try:
            before = self._gateway.run(
                SimulationRequest(**common, parameters=dict(current_values))
            )
        except (SimulatorGatewayError, ValueError) as error:
            raise ReplayGuardError(
                getattr(error, "code", "SIMULATOR_EXECUTION_FAILED"),
                getattr(error, "message", "模拟器基线执行失败。"),
            ) from error
        self._boundary_audit.counters["simulator_gateway_calls"] += 1
        self._boundary_audit.counters["baseline_runs"] += 1
        simulated_baseline_hash = _canonical_observations(before.measurements)
        if simulated_baseline_hash != imported_baseline_canonical_hash:
            raise ReplayGuardError(
                "BASELINE_REPRODUCTION_FAILED",
                "模拟器基线未能重现导入可观测数据。",
                expected_hash=imported_baseline_canonical_hash,
                actual_hash=simulated_baseline_hash,
                failed_validation="canonical_observation_hash",
            )
        try:
            after = self._gateway.run(
                SimulationRequest(**common, parameters=dict(proposed_values))
            )
        except (SimulatorGatewayError, ValueError) as error:
            raise ReplayGuardError(
                getattr(error, "code", "SIMULATOR_EXECUTION_FAILED"),
                getattr(error, "message", "模拟器干预执行失败。"),
            ) from error
        self._boundary_audit.counters["simulator_gateway_calls"] += 1
        self._boundary_audit.counters["intervention_runs"] += 1
        if before.binding != after.binding:
            raise ReplayGuardError(
                "PAIRED_SIMULATION_BINDING_MISMATCH",
                "配对模拟固定输入绑定不一致。",
            )
        changed_parameters = tuple(
            field
            for field in PARAMETER_FIELDS
            if current_values[field] != proposed_values[field]
        )
        before_metrics = derive_replay_metrics(before.measurements, control_limits)
        after_metrics = derive_replay_metrics(after.measurements, control_limits)
        evaluation = ReplayEvaluator().evaluate(before_metrics, after_metrics, evaluation_rules)
        after_hash = _canonical_observations(after.measurements)
        safe_binding = asdict(before.binding)
        safe_binding.pop("hidden_scenario_content_hash", None)
        baseline_input_hash = hashlib.sha256(
            canonical_json_bytes(
                {"binding": safe_binding, "parameters": dict(sorted(current_values.items()))}
            )
        ).hexdigest()
        intervention_input_hash = hashlib.sha256(
            canonical_json_bytes(
                {"binding": safe_binding, "parameters": dict(sorted(proposed_values.items()))}
            )
        ).hexdigest()
        return ReplayComputation(
            simulator_version=assets.simulator_version,
            replay_scenario_schema_version=assets.replay_scenario_schema_version,
            scenario_mapping_version=assets.scenario_mapping_version,
            scenario_ref_hash=scenario_ref_hash,
            disturbance_sequence_hash=assets.disturbance_sequence_hash,
            replay_seed_hash=before.binding.seed_hash,
            baseline_input_hash=baseline_input_hash,
            intervention_input_hash=intervention_input_hash,
            imported_baseline_canonical_hash=imported_baseline_canonical_hash,
            simulated_baseline_canonical_hash=simulated_baseline_hash,
            baseline_metrics=before_metrics,
            intervention_metrics=after_metrics,
            metric_deltas=metric_deltas(before_metrics, after_metrics),
            evaluation=evaluation,
            input_asset_hashes={
                "simulator_asset_manifest": assets.canonical_manifest_hash,
                "simulator_policy": assets.simulator_policy_hash,
                "disturbance_sequence": assets.disturbance_sequence_hash,
            },
            pairing_invariants={
                "hidden_scenario_hash": "MATCH",
                "disturbance_sequence_hash": "MATCH",
                "seed_hash": "MATCH",
                "sample_count": "MATCH",
                "timestamp_sequence": "MATCH",
                "simulator_version": "MATCH",
                "observable_schema": "MATCH",
                "only_changed_inputs": ",".join(changed_parameters),
            },
            before_observation_hash=simulated_baseline_hash,
            after_observation_hash=after_hash,
            hidden_binding_hash=before.binding.hidden_scenario_content_hash,
        )


__all__ = [
    "NO_DEVICE_WRITE_NOTICE",
    "REPLAY_DISCLAIMER",
    "REPLAY_DISCLAIMER_VERSION",
    "REPLAY_METRIC_DEFINITION_VERSION",
    "REPLAY_RESULT_CANONICALIZER_VERSION",
    "REPLAY_RESULT_VERSION",
    "BatchReplayMetrics",
    "EvaluationCheck",
    "FrozenReplayDict",
    "ReplayBoundaryAudit",
    "ReplayComputation",
    "ReplayEvaluation",
    "ReplayEvaluationRuleSnapshot",
    "ReplayEvaluator",
    "ReplayGuardError",
    "ReplayOrchestrator",
    "ReplayResult",
    "ReplayResultCanonicalizer",
    "ReplayStatus",
    "create_replay_result",
    "derive_replay_metrics",
    "deserialize_replay_result",
    "replay_result_business_payload",
]
