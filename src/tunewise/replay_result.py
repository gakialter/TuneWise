from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, is_dataclass, replace
from enum import StrEnum
from typing import Any, Mapping

from .importing import ObservableCanonicalizer
from .replay_contracts import (
    NO_DEVICE_WRITE_NOTICE,
    REPLAY_DISCLAIMER,
    REPLAY_DISCLAIMER_VERSION,
    REPLAY_RESULT_CANONICALIZER_VERSION,
    REPLAY_RESULT_VERSION,
    BatchReplayMetrics,
    EvaluationCheck,
    ReplayComputation,
    ReplayGuardError,
    ReplayResult,
    ReplayStatus,
)


def _plain(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return {key: _plain(item) for key, item in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    if isinstance(value, StrEnum):
        return value.value
    return value


class ReplayResultCanonicalizer:
    version = REPLAY_RESULT_CANONICALIZER_VERSION
    excluded_fields = frozenset(
        {
            "replay_result_id",
            "created_at",
            "completed_at",
            "request_tracking_id",
            "request_idempotency_key_hash",
            "disclaimer",
            "no_device_write_notice",
            "result_hash",
        }
    )

    def canonicalize(self, payload: Mapping[str, object]) -> bytes:
        stable = {
            key: _plain(value)
            for key, value in payload.items()
            if key not in self.excluded_fields
        }
        envelope = {
            "replay_result_canonicalizer_version": self.version,
            "business_content": stable,
        }
        return json.dumps(
            envelope,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    def sha256(self, payload: Mapping[str, object]) -> str:
        return hashlib.sha256(self.canonicalize(payload)).hexdigest()


def replay_result_business_payload(result: ReplayResult) -> dict[str, object]:
    return asdict(result)


def create_replay_result(
    *,
    task_id: str,
    confirmed_plan_id: str,
    confirmed_plan_hash: str,
    candidate_id: str,
    candidate_hash: str,
    request_idempotency_key: str,
    attempt_count: int,
    dataset_version: str,
    schema_version: str,
    generator_version: str,
    rule_set_version: str,
    model_version: str,
    computation: ReplayComputation,
    evaluation_rule_version: str,
    created_at: str,
    completed_at: str,
) -> ReplayResult:
    provisional = ReplayResult(
        replay_result_id="",
        replay_result_version=REPLAY_RESULT_VERSION,
        task_id=task_id,
        confirmed_plan_id=confirmed_plan_id,
        confirmed_plan_hash=confirmed_plan_hash,
        candidate_id=candidate_id,
        candidate_hash=candidate_hash,
        request_idempotency_key_hash=hashlib.sha256(
            request_idempotency_key.encode("utf-8")
        ).hexdigest(),
        replay_status=computation.evaluation.replay_status,
        attempt_count=attempt_count,
        dataset_version=dataset_version,
        schema_version=schema_version,
        generator_version=generator_version,
        rule_set_version=rule_set_version,
        model_version=model_version,
        simulator_version=computation.simulator_version,
        replay_scenario_schema_version=computation.replay_scenario_schema_version,
        scenario_mapping_version=computation.scenario_mapping_version,
        scenario_ref_hash=computation.scenario_ref_hash,
        disturbance_sequence_hash=computation.disturbance_sequence_hash,
        replay_seed_hash=computation.replay_seed_hash,
        baseline_input_hash=computation.baseline_input_hash,
        intervention_input_hash=computation.intervention_input_hash,
        canonicalizer_version=ObservableCanonicalizer.version,
        replay_result_canonicalizer_version=REPLAY_RESULT_CANONICALIZER_VERSION,
        imported_baseline_canonical_hash=computation.imported_baseline_canonical_hash,
        simulated_baseline_canonical_hash=computation.simulated_baseline_canonical_hash,
        baseline_reproduction_status="PASSED",
        baseline_metrics=computation.baseline_metrics,
        intervention_metrics=computation.intervention_metrics,
        metric_deltas=dict(sorted(computation.metric_deltas.items())),
        evaluation_checks=computation.evaluation.checks,
        replay_evaluation_rule_version=evaluation_rule_version,
        input_asset_hashes=dict(sorted(computation.input_asset_hashes.items())),
        pairing_invariants=dict(sorted(computation.pairing_invariants.items())),
        before_observation_hash=computation.before_observation_hash,
        after_observation_hash=computation.after_observation_hash,
        baseline_output_hash=computation.before_observation_hash,
        intervention_output_hash=computation.after_observation_hash,
        result_hash="",
        created_at=created_at,
        completed_at=completed_at,
        disclaimer_version=REPLAY_DISCLAIMER_VERSION,
        disclaimer=REPLAY_DISCLAIMER,
        no_device_write_notice=NO_DEVICE_WRITE_NOTICE,
    )
    result_hash = ReplayResultCanonicalizer().sha256(replay_result_business_payload(provisional))
    return replace(
        provisional,
        replay_result_id=f"tw-replay-result-{result_hash[:16]}",
        result_hash=result_hash,
    )


def deserialize_replay_result(payload: Mapping[str, Any]) -> ReplayResult:
    try:
        result = ReplayResult(
            **{
                **payload,
                "baseline_metrics": BatchReplayMetrics(**payload["baseline_metrics"]),
                "intervention_metrics": BatchReplayMetrics(**payload["intervention_metrics"]),
                "evaluation_checks": tuple(
                    EvaluationCheck(**item) for item in payload["evaluation_checks"]
                ),
            }
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ReplayGuardError("REPLAY_RESULT_HASH_MISMATCH", "已保存 ReplayResult 结构无效。") from error
    expected_hash = ReplayResultCanonicalizer().sha256(replay_result_business_payload(result))
    if (
        result.replay_result_version != REPLAY_RESULT_VERSION
        or result.replay_status not in {status.value for status in ReplayStatus}
        or result.attempt_count != 1
        or result.disclaimer_version != REPLAY_DISCLAIMER_VERSION
        or result.disclaimer != REPLAY_DISCLAIMER
        or result.no_device_write_notice != NO_DEVICE_WRITE_NOTICE
        or result.result_hash != expected_hash
        or result.replay_result_id != f"tw-replay-result-{expected_hash[:16]}"
    ):
        raise ReplayGuardError(
            "REPLAY_RESULT_HASH_MISMATCH",
            "已保存 ReplayResult 内容哈希不匹配。",
            expected_hash=expected_hash,
            actual_hash=result.result_hash,
        )
    return result
