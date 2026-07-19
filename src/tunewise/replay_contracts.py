from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping


REPLAY_RESULT_VERSION = "tw-replay-result-v1"
REPLAY_METRIC_DEFINITION_VERSION = "tw-replay-metrics-v1"
REPLAY_RESULT_CANONICALIZER_VERSION = "tw-replay-result-canonicalizer-v1"
REPLAY_DISCLAIMER_VERSION = "tw-replay-disclaimer-v1"
REPLAY_DISCLAIMER = "规则约束模拟环境中的离线回放结果，不代表真实产线良率改善。"
NO_DEVICE_WRITE_NOTICE = "本次回放仅比较固定模型、固定场景和固定扰动下的模拟结果，未向真实设备写入任何参数。"


class ReplayStatus(StrEnum):
    SUCCESS = "SUCCESS"
    PARTIAL_IMPROVEMENT = "PARTIAL_IMPROVEMENT"
    NO_IMPROVEMENT = "NO_IMPROVEMENT"
    REGRESSION = "REGRESSION"


class ReplayGuardError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 409,
        *,
        expected_hash: str | None = None,
        actual_hash: str | None = None,
        failed_validation: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.expected_hash = expected_hash
        self.actual_hash = actual_hash
        self.failed_validation = failed_validation


class FrozenReplayDict(dict[str, str]):
    @staticmethod
    def _immutable(*_args: object, **_kwargs: object) -> None:
        raise TypeError("ReplayResult mappings are immutable.")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable


@dataclass(frozen=True, slots=True)
class ReplayEvaluationRuleSnapshot:
    snapshot_version: str
    evaluation_rule_version: str
    center_regression_tolerance: str
    minimum_corner_min_improvement: str
    minimum_range_reduction: str
    minimum_std_reduction: str
    center_lower_limit: str
    corner_lower_limit: str
    asymmetry_limit: str


@dataclass(frozen=True, slots=True)
class BatchReplayMetrics:
    sample_count: int
    mtf_center_mean: str
    mtf_center_std: str
    mtf_lt_mean: str
    mtf_rt_mean: str
    mtf_lb_mean: str
    mtf_rb_mean: str
    corner_mtf_mean: str
    corner_mtf_min: str
    corner_mtf_range: str
    corner_mtf_std: str
    center_corner_gap: str
    control_limit_pass: bool
    target_anomaly_triggered: bool
    parameter_summary: Mapping[str, str]
    metric_definition_version: str
    standard_deviation_method: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameter_summary", FrozenReplayDict(self.parameter_summary))


@dataclass(frozen=True, slots=True)
class EvaluationCheck:
    check_id: str
    metric: str
    before_value: str | bool
    after_value: str | bool
    delta: str
    threshold: str | None
    tolerance: str | None
    status: str
    rule_version: str
    explanation_template_key: str


@dataclass(frozen=True, slots=True)
class ReplayEvaluation:
    replay_status: str
    checks: tuple[EvaluationCheck, ...]


@dataclass(frozen=True, slots=True)
class ReplayResult:
    replay_result_id: str
    replay_result_version: str
    task_id: str
    confirmed_plan_id: str
    confirmed_plan_hash: str
    candidate_id: str
    candidate_hash: str
    request_idempotency_key_hash: str
    replay_status: str
    attempt_count: int
    dataset_version: str
    schema_version: str
    generator_version: str
    rule_set_version: str
    model_version: str
    simulator_version: str
    replay_scenario_schema_version: str
    scenario_mapping_version: str
    scenario_ref_hash: str
    disturbance_sequence_hash: str
    replay_seed_hash: str
    baseline_input_hash: str
    intervention_input_hash: str
    canonicalizer_version: str
    replay_result_canonicalizer_version: str
    imported_baseline_canonical_hash: str
    simulated_baseline_canonical_hash: str
    baseline_reproduction_status: str
    baseline_metrics: BatchReplayMetrics
    intervention_metrics: BatchReplayMetrics
    metric_deltas: Mapping[str, str]
    evaluation_checks: tuple[EvaluationCheck, ...]
    replay_evaluation_rule_version: str
    input_asset_hashes: Mapping[str, str]
    pairing_invariants: Mapping[str, str]
    before_observation_hash: str
    after_observation_hash: str
    baseline_output_hash: str
    intervention_output_hash: str
    result_hash: str
    created_at: str
    completed_at: str
    disclaimer_version: str
    disclaimer: str
    no_device_write_notice: str

    def __post_init__(self) -> None:
        for field_name in ("metric_deltas", "input_asset_hashes", "pairing_invariants"):
            object.__setattr__(self, field_name, FrozenReplayDict(getattr(self, field_name)))


@dataclass(frozen=True, slots=True)
class ReplayComputation:
    simulator_version: str
    replay_scenario_schema_version: str
    scenario_mapping_version: str
    scenario_ref_hash: str
    disturbance_sequence_hash: str
    replay_seed_hash: str
    baseline_input_hash: str
    intervention_input_hash: str
    imported_baseline_canonical_hash: str
    simulated_baseline_canonical_hash: str
    baseline_metrics: BatchReplayMetrics
    intervention_metrics: BatchReplayMetrics
    metric_deltas: Mapping[str, str]
    evaluation: ReplayEvaluation
    input_asset_hashes: Mapping[str, str]
    pairing_invariants: Mapping[str, str]
    before_observation_hash: str
    after_observation_hash: str
    hidden_binding_hash: str

    def __post_init__(self) -> None:
        for field_name in ("metric_deltas", "input_asset_hashes", "pairing_invariants"):
            object.__setattr__(self, field_name, FrozenReplayDict(getattr(self, field_name)))


@dataclass(slots=True)
class ReplayBoundaryAudit:
    counters: dict[str, int]

    def __init__(self) -> None:
        self.counters = {
            "simulator_gateway_assemblies": 0,
            "simulator_gateway_calls": 0,
            "baseline_runs": 0,
            "intervention_runs": 0,
            "llm_calls": 0,
            "external_network_requests": 0,
            "real_device_calls": 0,
        }
