from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace
from typing import Any
from uuid import uuid4

from .parameter_planning import ParameterPlanCandidate


CONFIRMED_PLAN_VERSION = "tw-confirmed-plan-v1"
CONFIRMED_PLAN_FRESHNESS_VERSION = "tw-confirmed-plan-freshness-v1"


class FrozenDict(dict):
    @staticmethod
    def _immutable(*_args, **_kwargs):
        raise TypeError("ConfirmedPlan mappings are immutable.")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable


def canonical_hash(payload: object) -> str:
    content = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


@dataclass(frozen=True, slots=True)
class ConfirmedPlan:
    confirmed_plan_id: str
    confirmed_plan_version: str
    confirmed_plan_hash: str
    task_id: str
    planning_result_id: str
    planning_result_version: str
    candidate_id: str
    candidate_hash: str
    current_values: FrozenDict
    proposed_values: FrozenDict
    deltas: FrozenDict
    delta_ticks: FrozenDict
    parameter_family: str
    root_cause: str
    generation_type: str
    supporting_case_ids: tuple[str, ...]
    direction_evidence_hashes: tuple[str, ...]
    actor_id: str
    actor_role: str
    display_name: str
    confirmed_at: str
    status: str
    stale_reason_codes: tuple[str, ...]
    freshness_rule_version: str
    input_data_version: str
    input_measurement_hash: str
    current_parameter_hash: str
    detection_result_id: str
    detection_result_version: str
    diagnostic_result_id: str
    diagnostic_result_version: str
    case_retrieval_result_id: str | None
    case_retrieval_result_version: str | None
    control_limit_snapshot_version: str
    control_limit_snapshot_hash: str
    parameter_constraint_snapshot_version: str
    parameter_constraint_snapshot_hash: str
    direction_rule_version: str
    safety_rule_version: str
    planning_rule_version: str
    rule_set_version: str
    feature_definition_version: str
    model_version: str
    preprocessing_version: str
    approved_case_index_version: str | None
    source_asset_hashes: FrozenDict
    created_at: str


@dataclass(frozen=True, slots=True)
class AuditEvent:
    event_id: str
    task_id: str
    action: str
    actor_id: str
    actor_role: str
    display_name: str
    occurred_at: str
    result: str
    candidate_id: str | None
    candidate_hash: str | None
    confirmed_plan_id: str | None
    confirmed_plan_hash: str | None
    planning_result_id: str | None
    planning_result_version: str | None
    rule_set_version: str
    direction_rule_version: str | None
    safety_rule_version: str | None
    planning_rule_version: str | None
    control_limit_snapshot_version: str | None
    parameter_constraint_snapshot_version: str | None
    rejection_code: str | None
    expected_hash: str | None
    actual_hash: str | None
    expected_version: str | None
    actual_version: str | None
    replay_result_id: str | None = None
    replay_result_hash: str | None = None
    simulator_version: str | None = None
    evaluation_rule_version: str | None = None
    baseline_reproduction_status: str | None = None
    replay_status: str | None = None
    attempt_count: int | None = None


@dataclass(frozen=True, slots=True)
class FreshnessBinding:
    input_data_version: str
    input_measurement_hash: str
    current_parameter_hash: str
    detection_result_id: str
    detection_result_version: str
    diagnostic_result_id: str
    diagnostic_result_version: str
    case_retrieval_result_id: str | None
    case_retrieval_result_version: str | None
    planning_result_id: str
    planning_result_version: str
    candidate_hash: str
    control_limit_snapshot_version: str
    control_limit_snapshot_hash: str
    parameter_constraint_snapshot_version: str
    parameter_constraint_snapshot_hash: str
    direction_rule_version: str
    safety_rule_version: str
    planning_rule_version: str
    rule_set_version: str
    feature_definition_version: str
    model_version: str
    preprocessing_version: str
    approved_case_index_version: str | None
    source_asset_hashes: dict[str, str]


@dataclass(frozen=True, slots=True)
class FreshnessEvaluation:
    status: str
    stale_reason_codes: tuple[str, ...]
    freshness_rule_version: str = CONFIRMED_PLAN_FRESHNESS_VERSION

    @property
    def replay_eligible(self) -> bool:
        return self.status == "VALID"


class ConfirmedPlanFreshnessEvaluator:
    def evaluate(
        self,
        plan: ConfirmedPlan,
        current: FreshnessBinding,
    ) -> FreshnessEvaluation:
        if plan.status != "VALID":
            return FreshnessEvaluation("STALE", plan.stale_reason_codes)

        reasons: list[str] = []

        def changed(reason: str, *pairs: tuple[object, object]) -> None:
            if any(expected != actual for expected, actual in pairs) and reason not in reasons:
                reasons.append(reason)

        changed(
            "INPUT_DATA_CHANGED",
            (plan.input_data_version, current.input_data_version),
            (plan.input_measurement_hash, current.input_measurement_hash),
        )
        changed(
            "CURRENT_PARAMETER_CHANGED",
            (plan.current_parameter_hash, current.current_parameter_hash),
        )
        changed(
            "DETECTION_VERSION_CHANGED",
            (plan.detection_result_id, current.detection_result_id),
            (plan.detection_result_version, current.detection_result_version),
        )
        changed(
            "DIAGNOSTIC_VERSION_CHANGED",
            (plan.diagnostic_result_id, current.diagnostic_result_id),
            (plan.diagnostic_result_version, current.diagnostic_result_version),
        )
        changed(
            "RETRIEVAL_VERSION_CHANGED",
            (plan.case_retrieval_result_id, current.case_retrieval_result_id),
            (
                plan.case_retrieval_result_version,
                current.case_retrieval_result_version,
            ),
        )
        changed(
            "PLANNING_VERSION_CHANGED",
            (plan.planning_result_id, current.planning_result_id),
            (plan.planning_result_version, current.planning_result_version),
        )
        changed(
            "CANDIDATE_HASH_CHANGED",
            (plan.candidate_hash, current.candidate_hash),
        )
        changed(
            "CONTROL_LIMIT_SNAPSHOT_CHANGED",
            (
                plan.control_limit_snapshot_version,
                current.control_limit_snapshot_version,
            ),
            (plan.control_limit_snapshot_hash, current.control_limit_snapshot_hash),
        )
        changed(
            "PARAMETER_CONSTRAINT_SNAPSHOT_CHANGED",
            (
                plan.parameter_constraint_snapshot_version,
                current.parameter_constraint_snapshot_version,
            ),
            (
                plan.parameter_constraint_snapshot_hash,
                current.parameter_constraint_snapshot_hash,
            ),
        )
        changed(
            "RULE_VERSION_CHANGED",
            (plan.direction_rule_version, current.direction_rule_version),
            (plan.safety_rule_version, current.safety_rule_version),
            (plan.planning_rule_version, current.planning_rule_version),
            (plan.rule_set_version, current.rule_set_version),
            (plan.feature_definition_version, current.feature_definition_version),
            (plan.model_version, current.model_version),
            (plan.preprocessing_version, current.preprocessing_version),
            (
                plan.approved_case_index_version,
                current.approved_case_index_version,
            ),
        )
        if plan.source_asset_hashes != current.source_asset_hashes:
            asset_keys = set(plan.source_asset_hashes) | set(
                current.source_asset_hashes
            )
            changed_asset_keys = {
                key
                for key in asset_keys
                if plan.source_asset_hashes.get(key)
                != current.source_asset_hashes.get(key)
            }
            if any(key.startswith("supporting_case:") for key in changed_asset_keys):
                reasons.append("SUPPORTING_CASE_CHANGED")
            if any(
                not key.startswith("supporting_case:")
                for key in changed_asset_keys
            ):
                reasons.append("ASSET_HASH_MISMATCH")
        return FreshnessEvaluation(
            "STALE" if reasons else "VALID",
            tuple(reasons),
        )


class PlanConfirmationGuardError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 409,
        *,
        expected_hash: str | None = None,
        actual_hash: str | None = None,
        expected_version: str | None = None,
        actual_version: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.expected_hash = expected_hash
        self.actual_hash = actual_hash
        self.expected_version = expected_version
        self.actual_version = actual_version


def confirmed_plan_business_payload(plan: ConfirmedPlan) -> dict[str, Any]:
    payload = asdict(plan)
    for excluded in (
        "confirmed_plan_id",
        "confirmed_plan_hash",
        "task_id",
        "confirmed_at",
        "created_at",
        "status",
        "stale_reason_codes",
        "freshness_rule_version",
        "display_name",
    ):
        payload.pop(excluded)
    return payload


def create_confirmed_plan(
    *,
    task_id: str,
    planning_result_id: str,
    planning_result_version: str,
    candidate: ParameterPlanCandidate,
    actor_id: str,
    actor_role: str,
    display_name: str,
    confirmed_at: str,
    binding: FreshnessBinding,
) -> ConfirmedPlan:
    provisional = ConfirmedPlan(
        confirmed_plan_id="",
        confirmed_plan_version=CONFIRMED_PLAN_VERSION,
        confirmed_plan_hash="",
        task_id=task_id,
        planning_result_id=planning_result_id,
        planning_result_version=planning_result_version,
        candidate_id=candidate.candidate_id,
        candidate_hash=candidate.candidate_hash,
        current_values=FrozenDict(sorted(candidate.current_values.items())),
        proposed_values=FrozenDict(sorted(candidate.proposed_values.items())),
        deltas=FrozenDict(sorted(candidate.deltas.items())),
        delta_ticks=FrozenDict(sorted(candidate.delta_ticks.items())),
        parameter_family=candidate.parameter_family,
        root_cause=candidate.root_cause,
        generation_type=candidate.generation_type,
        supporting_case_ids=tuple(sorted(candidate.supporting_case_ids)),
        direction_evidence_hashes=tuple(
            sorted(item.evidence_hash for item in candidate.direction_evidence)
        ),
        actor_id=actor_id,
        actor_role=actor_role,
        display_name=display_name,
        confirmed_at=confirmed_at,
        status="VALID",
        stale_reason_codes=(),
        freshness_rule_version=CONFIRMED_PLAN_FRESHNESS_VERSION,
        input_data_version=binding.input_data_version,
        input_measurement_hash=binding.input_measurement_hash,
        current_parameter_hash=binding.current_parameter_hash,
        detection_result_id=binding.detection_result_id,
        detection_result_version=binding.detection_result_version,
        diagnostic_result_id=binding.diagnostic_result_id,
        diagnostic_result_version=binding.diagnostic_result_version,
        case_retrieval_result_id=binding.case_retrieval_result_id,
        case_retrieval_result_version=binding.case_retrieval_result_version,
        control_limit_snapshot_version=binding.control_limit_snapshot_version,
        control_limit_snapshot_hash=binding.control_limit_snapshot_hash,
        parameter_constraint_snapshot_version=(
            binding.parameter_constraint_snapshot_version
        ),
        parameter_constraint_snapshot_hash=binding.parameter_constraint_snapshot_hash,
        direction_rule_version=binding.direction_rule_version,
        safety_rule_version=binding.safety_rule_version,
        planning_rule_version=binding.planning_rule_version,
        rule_set_version=binding.rule_set_version,
        feature_definition_version=binding.feature_definition_version,
        model_version=binding.model_version,
        preprocessing_version=binding.preprocessing_version,
        approved_case_index_version=binding.approved_case_index_version,
        source_asset_hashes=FrozenDict(sorted(binding.source_asset_hashes.items())),
        created_at=confirmed_at,
    )
    content_hash = canonical_hash(confirmed_plan_business_payload(provisional))
    identity_hash = canonical_hash({"task_id": task_id, "content_hash": content_hash})
    return replace(
        provisional,
        confirmed_plan_id=f"tw-confirmed-plan-{identity_hash[:16]}",
        confirmed_plan_hash=content_hash,
    )


def deserialize_confirmed_plan(payload: dict[str, Any]) -> ConfirmedPlan:
    try:
        plan = ConfirmedPlan(
            **{
                **payload,
                "supporting_case_ids": tuple(payload["supporting_case_ids"]),
                "direction_evidence_hashes": tuple(
                    payload["direction_evidence_hashes"]
                ),
                "stale_reason_codes": tuple(payload["stale_reason_codes"]),
                "current_values": FrozenDict(payload["current_values"]),
                "proposed_values": FrozenDict(payload["proposed_values"]),
                "deltas": FrozenDict(payload["deltas"]),
                "delta_ticks": FrozenDict(payload["delta_ticks"]),
                "source_asset_hashes": FrozenDict(payload["source_asset_hashes"]),
            }
        )
    except (KeyError, TypeError, ValueError) as error:
        raise PlanConfirmationGuardError(
            "CONFIRMED_PLAN_HASH_MISMATCH",
            "已保存 ConfirmedPlan 结构或内容完整性校验失败。",
        ) from error
    expected_hash = canonical_hash(confirmed_plan_business_payload(plan))
    expected_id_hash = canonical_hash(
        {"task_id": plan.task_id, "content_hash": expected_hash}
    )
    if (
        plan.confirmed_plan_version != CONFIRMED_PLAN_VERSION
        or plan.status not in {"VALID", "STALE"}
        or (plan.status == "VALID" and plan.stale_reason_codes)
        or (plan.status == "STALE" and not plan.stale_reason_codes)
        or plan.confirmed_plan_hash != expected_hash
        or plan.confirmed_plan_id != f"tw-confirmed-plan-{expected_id_hash[:16]}"
    ):
        raise PlanConfirmationGuardError(
            "CONFIRMED_PLAN_HASH_MISMATCH",
            "已保存 ConfirmedPlan 内容哈希不匹配。",
            expected_hash=expected_hash,
            actual_hash=plan.confirmed_plan_hash,
        )
    return plan


def create_audit_event(
    *,
    task_id: str,
    actor_id: str,
    actor_role: str,
    display_name: str,
    occurred_at: str,
    result: str,
    rule_set_version: str,
    candidate_id: str | None,
    candidate_hash: str | None,
    plan: ConfirmedPlan | None = None,
    planning_result_id: str | None = None,
    planning_result_version: str | None = None,
    rejection_code: str | None = None,
    expected_hash: str | None = None,
    actual_hash: str | None = None,
    expected_version: str | None = None,
    actual_version: str | None = None,
) -> AuditEvent:
    return AuditEvent(
        event_id=f"tw-audit-{uuid4().hex}",
        task_id=task_id,
        action="CONFIRM_PARAMETER_PLAN",
        actor_id=actor_id,
        actor_role=actor_role,
        display_name=display_name,
        occurred_at=occurred_at,
        result=result,
        candidate_id=candidate_id,
        candidate_hash=candidate_hash,
        confirmed_plan_id=None if plan is None else plan.confirmed_plan_id,
        confirmed_plan_hash=None if plan is None else plan.confirmed_plan_hash,
        planning_result_id=(
            planning_result_id if plan is None else plan.planning_result_id
        ),
        planning_result_version=(
            planning_result_version if plan is None else plan.planning_result_version
        ),
        rule_set_version=rule_set_version,
        direction_rule_version=None if plan is None else plan.direction_rule_version,
        safety_rule_version=None if plan is None else plan.safety_rule_version,
        planning_rule_version=None if plan is None else plan.planning_rule_version,
        control_limit_snapshot_version=(
            None if plan is None else plan.control_limit_snapshot_version
        ),
        parameter_constraint_snapshot_version=(
            None if plan is None else plan.parameter_constraint_snapshot_version
        ),
        rejection_code=rejection_code,
        expected_hash=expected_hash,
        actual_hash=actual_hash,
        expected_version=expected_version,
        actual_version=actual_version,
    )
