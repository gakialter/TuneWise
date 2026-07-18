from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any


TICK_SIZE = Decimal("0.050000")
DIRECTION_RULE_VERSION = "tw-direction-rules-v1"
SAFETY_RULE_VERSION = "tw-parameter-safety-v1"
PLANNING_RESULT_VERSION = "tw-parameter-planning-result-v1"
PLANNING_RULE_VERSION = "tw-parameter-planning-v1"


@dataclass(frozen=True, slots=True)
class ParameterConstraint:
    parameter_name: str
    nominal_value: str
    minimum: str
    maximum: str
    step: str
    maximum_single_plan_delta: str


@dataclass(frozen=True, slots=True)
class ParameterConstraintSnapshot:
    snapshot_version: str
    product_model: str
    rule_set_version: str
    constraints: tuple[ParameterConstraint, ...]

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> ParameterConstraintSnapshot:
        constraints_payload = payload["constraints"]
        return cls(
            snapshot_version=payload["snapshot_version"],
            product_model=payload["product_model"],
            rule_set_version=payload["rule_set_version"],
            constraints=tuple(
                ParameterConstraint(parameter_name=name, **constraints_payload[name])
                for name in sorted(constraints_payload)
            ),
        )

    def by_name(self) -> dict[str, ParameterConstraint]:
        return {constraint.parameter_name: constraint for constraint in self.constraints}


@dataclass(frozen=True, slots=True)
class ParameterDirectionEvidence:
    parameter_name: str
    current_value: str
    current_tick: int | None
    nominal_value: str
    nominal_tick: int
    recommended_direction: str
    supporting_features: tuple[str, ...]
    supporting_rules: tuple[str, ...]
    conflicting_features: tuple[str, ...]
    conflict_status: str
    diagnostic_result_version: str
    feature_definition_version: str
    direction_rule_version: str
    evidence_hash: str


@dataclass(frozen=True, slots=True)
class ValidationCheck:
    check_code: str
    status: str
    detail: str


@dataclass(frozen=True, slots=True)
class ParameterPlanCandidate:
    candidate_id: str
    generation_type: str
    generation_sources: tuple[str, ...]
    root_cause: str
    parameter_family: str
    current_values: dict[str, str]
    proposed_values: dict[str, str]
    current_ticks: dict[str, int | None]
    proposed_ticks: dict[str, int | None]
    deltas: dict[str, str]
    delta_ticks: dict[str, int | None]
    total_absolute_delta_ticks: int
    direction_evidence: tuple[ParameterDirectionEvidence, ...]
    supporting_case_ids: tuple[str, ...]
    supporting_case_count: int
    constraint_snapshot_version: str
    rule_set_version: str
    direction_rule_version: str
    safety_rule_version: str
    diagnostic_result_version: str
    case_retrieval_result_version: str | None
    validation_checks: tuple[ValidationCheck, ...]
    validation_status: str
    rejection_reasons: tuple[str, ...]
    candidate_hash: str


@dataclass(frozen=True, slots=True)
class SafetyVersionContext:
    constraint_snapshot_version: str
    rule_set_version: str
    direction_rule_version: str
    safety_rule_version: str
    diagnostic_result_version: str
    case_retrieval_result_version: str | None


@dataclass(frozen=True, slots=True)
class SafetyValidationResult:
    validation_status: str
    validation_checks: tuple[ValidationCheck, ...]
    rejection_reasons: tuple[str, ...]
    safety_rule_version: str
    constraint_snapshot_version: str
    validated_candidate_hash: str


@dataclass(frozen=True, slots=True)
class AxisDirectionRule:
    parameter_name: str
    root_cause: str
    feature_name: str
    sign_relation: str
    rule_id: str


@dataclass(frozen=True, slots=True)
class DirectionRuleSet:
    direction_rule_version: str
    rule_set_version: str
    minimum_spatial_support: str
    axis_rules: tuple[AxisDirectionRule, ...]
    z_rule: dict[str, Any]

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> DirectionRuleSet:
        return cls(
            direction_rule_version=payload["direction_rule_version"],
            rule_set_version=payload["rule_set_version"],
            minimum_spatial_support=payload["minimum_spatial_support"],
            axis_rules=tuple(
                AxisDirectionRule(parameter_name=name, **rule)
                for name, rule in sorted(payload["axis_rules"].items())
            ),
            z_rule=dict(payload["z_rule"]),
        )


@dataclass(frozen=True, slots=True)
class ParameterSafetyPolicy:
    safety_rule_version: str
    rule_set_version: str
    tick_size: str
    maximum_adjusted_parameter_count: int
    parameter_families: tuple[tuple[str, tuple[str, ...]], ...]
    top1_allowed_families: tuple[tuple[str, str], ...]

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> ParameterSafetyPolicy:
        return cls(
            safety_rule_version=payload["safety_rule_version"],
            rule_set_version=payload["rule_set_version"],
            tick_size=payload["tick_size"],
            maximum_adjusted_parameter_count=payload[
                "maximum_adjusted_parameter_count"
            ],
            parameter_families=tuple(
                (family, tuple(parameters))
                for family, parameters in sorted(
                    payload["parameter_families"].items()
                )
            ),
            top1_allowed_families=tuple(
                sorted(payload["top1_allowed_families"].items())
            ),
        )

    def family_for_parameter(self, parameter_name: str) -> str | None:
        return next(
            (
                family
                for family, parameters in self.parameter_families
                if parameter_name in parameters
            ),
            None,
        )

    def family_for_root_cause(self, root_cause: str) -> str | None:
        return dict(self.top1_allowed_families).get(root_cause)

    def parameters_for_family(self, family: str) -> frozenset[str]:
        return frozenset(dict(self.parameter_families).get(family, ()))


@dataclass(frozen=True, slots=True)
class ParameterGenerationPolicy:
    planning_rule_version: str
    rule_set_version: str
    generation_ticks: tuple[tuple[str, int], ...]
    maximum_candidate_count: int
    sort_order: tuple[str, ...]
    case_action_version: str

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> ParameterGenerationPolicy:
        return cls(
            planning_rule_version=payload["planning_rule_version"],
            rule_set_version=payload["rule_set_version"],
            generation_ticks=tuple(sorted(payload["generation_ticks"].items())),
            maximum_candidate_count=payload["maximum_candidate_count"],
            sort_order=tuple(payload["sort_order"]),
            case_action_version=payload["case_action_version"],
        )

    def ticks_for(self, generation_type: str) -> int:
        return dict(self.generation_ticks)[generation_type]

    def candidate_sort_key(
        self, candidate: ParameterPlanCandidate
    ) -> tuple[int, int, str]:
        expected_order = (
            "total_absolute_delta_ticks:ASC",
            "supporting_case_count:DESC",
            "candidate_id:ASC",
        )
        if self.sort_order != expected_order:
            raise ValueError("不支持的参数候选排序规则。")
        return (
            candidate.total_absolute_delta_ticks,
            -candidate.supporting_case_count,
            candidate.candidate_id,
        )


DEFAULT_SAFETY_POLICY = ParameterSafetyPolicy.from_payload(
    {
        "safety_rule_version": SAFETY_RULE_VERSION,
        "rule_set_version": "tw-rules-v1",
        "tick_size": "0.050000",
        "maximum_adjusted_parameter_count": 2,
        "parameter_families": {
            "XY_OFFSET": ["x_offset", "y_offset"],
            "PITCH_ROLL": ["pitch", "roll"],
            "Z_OFFSET": ["z_offset"],
        },
        "top1_allowed_families": {
            "PLANE_TILT": "PITCH_ROLL",
            "XY_DECENTER": "XY_OFFSET",
            "Z_DEFOCUS_CONDITIONAL": "Z_OFFSET",
        },
    }
)

DEFAULT_GENERATION_POLICY = ParameterGenerationPolicy.from_payload(
    {
        "planning_rule_version": PLANNING_RULE_VERSION,
        "rule_set_version": "tw-rules-v1",
        "generation_ticks": {"CONSERVATIVE": 1, "STANDARD": 2},
        "maximum_candidate_count": 3,
        "sort_order": [
            "total_absolute_delta_ticks:ASC",
            "supporting_case_count:DESC",
            "candidate_id:ASC",
        ],
        "case_action_version": "tw-approved-case-action-v1",
    }
)


@dataclass(frozen=True, slots=True)
class DirectionEvidenceDecision:
    direction_evidence: tuple[ParameterDirectionEvidence, ...]
    refusal_code: str | None

    @property
    def usable_evidence(self) -> tuple[ParameterDirectionEvidence, ...]:
        return tuple(
            item
            for item in self.direction_evidence
            if item.conflict_status == "NO_CONFLICT"
        )


@dataclass(frozen=True, slots=True)
class HistoricalCaseAction:
    case_id: str
    status: str
    source_partition: str
    source_partition_id: str
    station_type: str
    product_model: str
    reviewed_root_cause: str
    parameter_family: str
    parameter_delta_ticks: dict[str, int]
    action_version: str
    historical_safety_status: str
    historical_safety_rule_version: str
    historical_simulated_result_status: str
    center_within_tolerance: bool
    feature_definition_version: str
    rule_set_version: str
    retrieval_rule_version: str
    case_schema_version: str


@dataclass(frozen=True, slots=True)
class CandidateGenerationDecision:
    ordered_candidates: tuple[ParameterPlanCandidate, ...]
    rejected_candidates: tuple[ParameterPlanCandidate, ...]
    case_guidance_status: str


class ParameterPlanningAssetError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class ParameterPlanningGuardError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 409,
        *,
        supporting_evidence: tuple[str, ...] = (),
        recommended_inspection_actions: tuple[str, ...] = (),
        rule_set_version: str = "tw-rules-v1",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.supporting_evidence = supporting_evidence
        self.recommended_inspection_actions = recommended_inspection_actions
        self.rule_set_version = rule_set_version


@dataclass(frozen=True, slots=True)
class ParameterPlanningRefusalRecord:
    refusal_record_id: str
    task_id: str
    requested_diagnostic_result_id: str
    requested_case_retrieval_result_id: str | None
    refusal_code: str
    refusal_message: str
    supporting_evidence: tuple[str, ...]
    recommended_inspection_actions: tuple[str, ...]
    rule_set_version: str
    result_hash: str
    created_at: str


def record_parameter_planning_refusal(
    *,
    task_id: str,
    requested_diagnostic_result_id: str,
    requested_case_retrieval_result_id: str | None,
    refusal_code: str,
    refusal_message: str,
    supporting_evidence: tuple[str, ...],
    recommended_inspection_actions: tuple[str, ...],
    rule_set_version: str,
    created_at: str,
) -> ParameterPlanningRefusalRecord:
    business_payload = {
        "refusal_code": refusal_code,
        "refusal_message": refusal_message,
        "supporting_evidence": supporting_evidence,
        "recommended_inspection_actions": recommended_inspection_actions,
        "rule_set_version": rule_set_version,
    }
    result_hash = _canonical_hash(business_payload)
    identity_hash = _canonical_hash(
        {
            "task_id": task_id,
            "requested_diagnostic_result_id": requested_diagnostic_result_id,
            "requested_case_retrieval_result_id": requested_case_retrieval_result_id,
            "result_hash": result_hash,
        }
    )
    return ParameterPlanningRefusalRecord(
        refusal_record_id=f"tw-parameter-planning-refusal-{identity_hash[:16]}",
        task_id=task_id,
        requested_diagnostic_result_id=requested_diagnostic_result_id,
        requested_case_retrieval_result_id=requested_case_retrieval_result_id,
        refusal_code=refusal_code,
        refusal_message=refusal_message,
        supporting_evidence=supporting_evidence,
        recommended_inspection_actions=recommended_inspection_actions,
        rule_set_version=rule_set_version,
        result_hash=result_hash,
        created_at=created_at,
    )


@dataclass(frozen=True, slots=True)
class ParameterPlanningAssets:
    manifest: dict[str, Any]
    direction_rules: DirectionRuleSet
    safety_policy: ParameterSafetyPolicy
    planning_policy: ParameterGenerationPolicy
    manifest_hash: str
    expected_parameter_constraint_snapshot_hash: str


@dataclass(frozen=True, slots=True)
class ParameterPlanningResultRecord:
    planning_result_version: str
    planning_result_id: str
    task_id: str
    diagnostic_result_id: str
    case_retrieval_result_id: str | None
    top1_root_cause: str
    direction_evidence: tuple[ParameterDirectionEvidence, ...]
    ordered_candidates: tuple[ParameterPlanCandidate, ...]
    parameter_constraints: tuple[ParameterConstraint, ...]
    planning_status: str
    refusal_code: str | None
    refusal_message: str | None
    supporting_evidence: tuple[str, ...]
    recommended_inspection_actions: tuple[str, ...]
    case_guidance_status: str
    input_hash: str
    result_hash: str
    created_at: str
    constraint_snapshot_version: str
    rule_set_version: str
    direction_rule_version: str
    safety_rule_version: str
    planning_rule_version: str
    feature_definition_version: str
    diagnostic_result_version: str
    case_retrieval_result_version: str | None
    planning_asset_manifest_hash: str


def record_parameter_planning(
    *,
    task_id: str,
    diagnostic_result_id: str,
    case_retrieval_result_id: str | None,
    top1_root_cause: str,
    direction_evidence: tuple[ParameterDirectionEvidence, ...],
    ordered_candidates: tuple[ParameterPlanCandidate, ...],
    parameter_constraints: tuple[ParameterConstraint, ...],
    planning_status: str,
    refusal_code: str | None,
    refusal_message: str | None,
    supporting_evidence: tuple[str, ...],
    recommended_inspection_actions: tuple[str, ...],
    case_guidance_status: str,
    input_bindings: dict[str, Any],
    constraint_snapshot_version: str,
    rule_set_version: str,
    feature_definition_version: str,
    diagnostic_result_version: str,
    case_retrieval_result_version: str | None,
    planning_asset_manifest_hash: str,
    created_at: str,
) -> ParameterPlanningResultRecord:
    input_hash = parameter_planning_input_hash(input_bindings)
    business_payload = {
        "planning_result_version": PLANNING_RESULT_VERSION,
        "top1_root_cause": top1_root_cause,
        "direction_evidence": [asdict(item) for item in direction_evidence],
        "ordered_candidates": [asdict(item) for item in ordered_candidates],
        "parameter_constraints": [asdict(item) for item in parameter_constraints],
        "planning_status": planning_status,
        "refusal_code": refusal_code,
        "refusal_message": refusal_message,
        "supporting_evidence": supporting_evidence,
        "recommended_inspection_actions": recommended_inspection_actions,
        "case_guidance_status": case_guidance_status,
        "input_hash": input_hash,
        "constraint_snapshot_version": constraint_snapshot_version,
        "rule_set_version": rule_set_version,
        "direction_rule_version": DIRECTION_RULE_VERSION,
        "safety_rule_version": SAFETY_RULE_VERSION,
        "planning_rule_version": PLANNING_RULE_VERSION,
        "feature_definition_version": feature_definition_version,
        "diagnostic_result_version": diagnostic_result_version,
        "case_retrieval_result_version": case_retrieval_result_version,
        "planning_asset_manifest_hash": planning_asset_manifest_hash,
    }
    result_hash = _canonical_hash(business_payload)
    planning_result_id = _planning_result_id(task_id, result_hash)
    return ParameterPlanningResultRecord(
        planning_result_version=PLANNING_RESULT_VERSION,
        planning_result_id=planning_result_id,
        task_id=task_id,
        diagnostic_result_id=diagnostic_result_id,
        case_retrieval_result_id=case_retrieval_result_id,
        top1_root_cause=top1_root_cause,
        direction_evidence=direction_evidence,
        ordered_candidates=ordered_candidates,
        parameter_constraints=parameter_constraints,
        planning_status=planning_status,
        refusal_code=refusal_code,
        refusal_message=refusal_message,
        supporting_evidence=supporting_evidence,
        recommended_inspection_actions=recommended_inspection_actions,
        case_guidance_status=case_guidance_status,
        input_hash=input_hash,
        result_hash=result_hash,
        created_at=created_at,
        constraint_snapshot_version=constraint_snapshot_version,
        rule_set_version=rule_set_version,
        direction_rule_version=DIRECTION_RULE_VERSION,
        safety_rule_version=SAFETY_RULE_VERSION,
        planning_rule_version=PLANNING_RULE_VERSION,
        feature_definition_version=feature_definition_version,
        diagnostic_result_version=diagnostic_result_version,
        case_retrieval_result_version=case_retrieval_result_version,
        planning_asset_manifest_hash=planning_asset_manifest_hash,
    )


def deserialize_parameter_planning_result(
    payload: dict[str, Any],
) -> ParameterPlanningResultRecord:
    def evidence(item: dict[str, Any]) -> ParameterDirectionEvidence:
        return ParameterDirectionEvidence(**item)

    def candidate(item: dict[str, Any]) -> ParameterPlanCandidate:
        return ParameterPlanCandidate(
            **{
                **item,
                "generation_sources": tuple(item["generation_sources"]),
                "direction_evidence": tuple(
                    evidence(value) for value in item["direction_evidence"]
                ),
                "supporting_case_ids": tuple(item["supporting_case_ids"]),
                "validation_checks": tuple(
                    ValidationCheck(**value) for value in item["validation_checks"]
                ),
                "rejection_reasons": tuple(item["rejection_reasons"]),
            }
        )

    try:
        record = ParameterPlanningResultRecord(
            **{
                **payload,
                "direction_evidence": tuple(
                    evidence(item) for item in payload["direction_evidence"]
                ),
                "ordered_candidates": tuple(
                    candidate(item) for item in payload["ordered_candidates"]
                ),
                "parameter_constraints": tuple(
                    ParameterConstraint(**item)
                    for item in payload["parameter_constraints"]
                ),
                "supporting_evidence": tuple(payload["supporting_evidence"]),
                "recommended_inspection_actions": tuple(
                    payload["recommended_inspection_actions"]
                ),
            }
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ParameterPlanningGuardError(
            "PLANNING_RESULT_HASH_MISMATCH", "已保存参数规划结果完整性校验失败。"
        ) from error
    expected = record_parameter_planning(
        task_id=record.task_id,
        diagnostic_result_id=record.diagnostic_result_id,
        case_retrieval_result_id=record.case_retrieval_result_id,
        top1_root_cause=record.top1_root_cause,
        direction_evidence=record.direction_evidence,
        ordered_candidates=record.ordered_candidates,
        parameter_constraints=record.parameter_constraints,
        planning_status=record.planning_status,
        refusal_code=record.refusal_code,
        refusal_message=record.refusal_message,
        supporting_evidence=record.supporting_evidence,
        recommended_inspection_actions=record.recommended_inspection_actions,
        case_guidance_status=record.case_guidance_status,
        input_bindings={"stored_input_hash": record.input_hash},
        constraint_snapshot_version=record.constraint_snapshot_version,
        rule_set_version=record.rule_set_version,
        feature_definition_version=record.feature_definition_version,
        diagnostic_result_version=record.diagnostic_result_version,
        case_retrieval_result_version=record.case_retrieval_result_version,
        planning_asset_manifest_hash=record.planning_asset_manifest_hash,
        created_at=record.created_at,
    )
    business_payload = asdict(record)
    for excluded in (
        "planning_result_id",
        "task_id",
        "diagnostic_result_id",
        "case_retrieval_result_id",
        "result_hash",
        "created_at",
    ):
        business_payload.pop(excluded)
    expected_result_hash = _canonical_hash(business_payload)
    if (
        record.planning_result_version != PLANNING_RESULT_VERSION
        or record.planning_result_id
        != _planning_result_id(record.task_id, record.result_hash)
        or record.result_hash != expected_result_hash
        or expected.planning_result_version != record.planning_result_version
    ):
        raise ParameterPlanningGuardError(
            "PLANNING_RESULT_HASH_MISMATCH", "已保存参数规划结果完整性校验失败。"
        )
    return record


class ParameterPlanningAssetLoader:
    REQUIRED_FILES = (
        "direction-rules.json",
        "planning-rules.json",
        "safety-rules.json",
    )

    def __init__(self, root: Path, expected_manifest_hash: str) -> None:
        self._root = root.resolve()
        self._expected_manifest_hash = expected_manifest_hash

    def load(self) -> ParameterPlanningAssets:
        manifest_bytes = self._read("manifest.json")
        manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
        if manifest_hash != self._expected_manifest_hash:
            raise ParameterPlanningAssetError(
                "PLANNING_MANIFEST_HASH_MISMATCH",
                "参数规划资产 Manifest 哈希与受信任版本不一致。",
            )
        try:
            manifest = json.loads(manifest_bytes)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ParameterPlanningAssetError(
                "PLANNING_MANIFEST_INVALID", "参数规划资产 Manifest 无效。"
            ) from error
        expected_manifest = {
            "manifest_version": "1",
            "asset_version": "tw-parameter-planning-assets-v1",
            "direction_rule_version": DIRECTION_RULE_VERSION,
            "safety_rule_version": SAFETY_RULE_VERSION,
            "planning_rule_version": PLANNING_RULE_VERSION,
            "planning_result_version": PLANNING_RESULT_VERSION,
            "rule_set_version": "tw-rules-v1",
            "feature_definition_version": "tw-feature-definition-v1",
        }
        if any(manifest.get(key) != value for key, value in expected_manifest.items()):
            raise ParameterPlanningAssetError(
                "PLANNING_MANIFEST_VERSION_STALE", "参数规划资产版本不是冻结版本。"
            )
        files = manifest.get("files")
        if not isinstance(files, dict) or set(files) != set(self.REQUIRED_FILES):
            raise ParameterPlanningAssetError(
                "PLANNING_MANIFEST_INVALID", "参数规划资产文件清单无效。"
            )
        payloads: dict[str, dict[str, Any]] = {}
        for name in self.REQUIRED_FILES:
            content = self._read(name)
            if hashlib.sha256(content).hexdigest() != files[name]:
                raise ParameterPlanningAssetError(
                    "PLANNING_ASSET_HASH_MISMATCH", "参数规划规则资产内容哈希不匹配。"
                )
            try:
                payload = json.loads(content)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ParameterPlanningAssetError(
                    "PLANNING_ASSET_INVALID", "参数规划规则资产格式无效。"
                ) from error
            if not isinstance(payload, dict):
                raise ParameterPlanningAssetError(
                    "PLANNING_ASSET_INVALID", "参数规划规则资产结构无效。"
                )
            payloads[name] = payload
        try:
            direction_rules = DirectionRuleSet.from_payload(
                payloads["direction-rules.json"]
            )
            safety_policy = ParameterSafetyPolicy.from_payload(
                payloads["safety-rules.json"]
            )
            planning_policy = ParameterGenerationPolicy.from_payload(
                payloads["planning-rules.json"]
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ParameterPlanningAssetError(
                "PLANNING_ASSET_INVALID", "参数规划规则资产结构无效。"
            ) from error
        if (
            direction_rules.direction_rule_version != DIRECTION_RULE_VERSION
            or direction_rules.rule_set_version != manifest["rule_set_version"]
            or safety_policy != DEFAULT_SAFETY_POLICY
            or safety_policy.rule_set_version != manifest["rule_set_version"]
            or planning_policy != DEFAULT_GENERATION_POLICY
            or planning_policy.rule_set_version != manifest["rule_set_version"]
        ):
            raise ParameterPlanningAssetError(
                "PLANNING_ASSET_VERSION_STALE", "参数规划规则资产内容不是冻结版本。"
            )
        snapshot_hash = manifest.get("expected_parameter_constraint_snapshot_hash")
        if not isinstance(snapshot_hash, str) or len(snapshot_hash) != 64:
            raise ParameterPlanningAssetError(
                "PLANNING_MANIFEST_INVALID", "参数约束快照受信任哈希缺失。"
            )
        return ParameterPlanningAssets(
            manifest=manifest,
            direction_rules=direction_rules,
            safety_policy=safety_policy,
            planning_policy=planning_policy,
            manifest_hash=manifest_hash,
            expected_parameter_constraint_snapshot_hash=snapshot_hash,
        )

    def _read(self, name: str) -> bytes:
        path = (self._root / name).resolve()
        if not path.is_relative_to(self._root):
            raise ParameterPlanningAssetError(
                "PLANNING_ASSET_PATH_FORBIDDEN", "参数规划资产路径越界。"
            )
        try:
            return path.read_bytes()
        except FileNotFoundError as error:
            raise ParameterPlanningAssetError(
                "PLANNING_ASSET_MISSING", "参数规划规则资产缺失。"
            ) from error


def _canonical_hash(payload: object) -> str:
    content = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def parameter_planning_input_hash(input_bindings: dict[str, Any]) -> str:
    business_bindings = {
        key: value
        for key, value in input_bindings.items()
        if key
        not in {
            "task_id",
            "diagnostic_result_id",
            "case_retrieval_result_id",
        }
    }
    return _canonical_hash(business_bindings)


def _planning_result_id(task_id: str, result_hash: str) -> str:
    identity_hash = _canonical_hash(
        {"task_id": task_id, "result_hash": result_hash}
    )
    return f"tw-parameter-planning-{identity_hash[:16]}"


def candidate_content_hash(candidate: ParameterPlanCandidate) -> str:
    payload = asdict(candidate)
    for excluded in (
        "candidate_id",
        "candidate_hash",
        "validation_checks",
        "validation_status",
        "rejection_reasons",
    ):
        payload.pop(excluded)
    return _canonical_hash(payload)


def _decimal(value: str) -> Decimal | None:
    try:
        parsed = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not parsed.is_finite() or parsed.as_tuple().exponent < -6:
        return None
    return parsed


def _observable_decimal(value: str) -> Decimal | None:
    try:
        parsed = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _tick(value: Decimal, step: Decimal, nominal: Decimal) -> int | None:
    ticks = (value - nominal) / step
    integral = ticks.to_integral_value()
    return int(integral) if ticks == integral else None


def validate_current_parameter_values(
    current_values: dict[str, str],
    snapshot: ParameterConstraintSnapshot,
) -> str | None:
    constraints = snapshot.by_name()
    if set(current_values) != set(constraints):
        return "CURRENT_PARAMETER_SET_INVALID"
    for name, raw_value in current_values.items():
        constraint = constraints[name]
        current = _decimal(raw_value)
        nominal = _decimal(constraint.nominal_value)
        minimum = _decimal(constraint.minimum)
        maximum = _decimal(constraint.maximum)
        step = _decimal(constraint.step)
        if any(value is None for value in (current, nominal, minimum, maximum, step)):
            return "CURRENT_VALUE_PRECISION_INVALID"
        if current < minimum or current > maximum:
            return "CURRENT_VALUE_OUT_OF_RANGE"
        if step <= 0 or _tick(current, step, nominal) is None:
            return "CURRENT_VALUE_OFF_GRID"
    return None


def _format_decimal(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.000001')):.6f}"


def direction_evidence_hash(evidence: ParameterDirectionEvidence) -> str:
    payload = asdict(evidence)
    payload.pop("evidence_hash")
    return _canonical_hash(payload)


class DirectionEvidenceGenerator:
    def __init__(self, rules: DirectionRuleSet) -> None:
        self._rules = rules

    def generate(
        self,
        *,
        root_cause: str,
        current_values: dict[str, str],
        features: dict[str, str],
        snapshot: ParameterConstraintSnapshot,
        diagnostic_result_version: str,
        feature_definition_version: str,
        z_gate_passed: bool,
    ) -> DirectionEvidenceDecision:
        if root_cause == "Z_DEFOCUS_CONDITIONAL":
            return self._generate_z(
                current_values=current_values,
                features=features,
                snapshot=snapshot,
                diagnostic_result_version=diagnostic_result_version,
                feature_definition_version=feature_definition_version,
                z_gate_passed=z_gate_passed,
            )
        minimum_support = _decimal(self._rules.minimum_spatial_support)
        if minimum_support is None or minimum_support <= 0:
            return DirectionEvidenceDecision((), "DIRECTION_RULE_INVALID")
        constraints = snapshot.by_name()
        evidence: list[ParameterDirectionEvidence] = []
        for rule in self._rules.axis_rules:
            if rule.root_cause != root_cause or rule.parameter_name not in current_values:
                continue
            constraint = constraints.get(rule.parameter_name)
            current = _decimal(current_values[rule.parameter_name])
            feature = _observable_decimal(features.get(rule.feature_name, ""))
            if constraint is None or current is None or feature is None:
                continue
            nominal = _decimal(constraint.nominal_value)
            step = _decimal(constraint.step)
            if nominal is None or step is None or current == nominal:
                continue
            current_tick = _tick(current, step, nominal)
            if current_tick is None:
                continue
            spatial_supported = abs(feature) >= minimum_support
            signs_match = (current - nominal) * feature > 0
            relation_supported = (
                signs_match
                if rule.sign_relation == "SAME_SIGN"
                else not signs_match
                if rule.sign_relation == "OPPOSITE_SIGN"
                else False
            )
            conflict_status = (
                "NO_CONFLICT"
                if spatial_supported and relation_supported
                else "CONFLICT"
                if spatial_supported
                else "INSUFFICIENT_SUPPORT"
            )
            item = ParameterDirectionEvidence(
                parameter_name=rule.parameter_name,
                current_value=_format_decimal(current),
                current_tick=current_tick,
                nominal_value=_format_decimal(nominal),
                nominal_tick=0,
                recommended_direction=(
                    "DECREASE" if current > nominal else "INCREASE"
                ),
                supporting_features=(
                    (f"{rule.feature_name}={_format_decimal(feature)}",)
                    if conflict_status == "NO_CONFLICT"
                    else ()
                ),
                supporting_rules=(
                    (rule.rule_id,) if conflict_status == "NO_CONFLICT" else ()
                ),
                conflicting_features=(
                    ()
                    if conflict_status == "NO_CONFLICT"
                    else (f"{rule.feature_name}={_format_decimal(feature)}",)
                ),
                conflict_status=conflict_status,
                diagnostic_result_version=diagnostic_result_version,
                feature_definition_version=feature_definition_version,
                direction_rule_version=self._rules.direction_rule_version,
                evidence_hash="",
            )
            evidence.append(
                ParameterDirectionEvidence(
                    **{
                        **asdict(item),
                        "evidence_hash": direction_evidence_hash(item),
                    }
                )
            )
        ordered = tuple(sorted(evidence, key=lambda item: item.parameter_name))
        refusal = None if any(item.conflict_status == "NO_CONFLICT" for item in ordered) else "NO_CLEAR_DIRECTION_EVIDENCE"
        return DirectionEvidenceDecision(ordered, refusal)

    def _generate_z(
        self,
        *,
        current_values: dict[str, str],
        features: dict[str, str],
        snapshot: ParameterConstraintSnapshot,
        diagnostic_result_version: str,
        feature_definition_version: str,
        z_gate_passed: bool,
    ) -> DirectionEvidenceDecision:
        if not z_gate_passed:
            return DirectionEvidenceDecision((), "Z_GATE_NOT_PASSED")
        constraint = snapshot.by_name().get("z_offset")
        current = _decimal(current_values.get("z_offset", ""))
        if constraint is None or current is None:
            return DirectionEvidenceDecision((), "NO_CLEAR_DIRECTION_EVIDENCE")
        nominal = _decimal(constraint.nominal_value)
        step = _decimal(constraint.step)
        feature_names = tuple(self._rules.z_rule.get("supporting_features", ()))
        feature_values = tuple(
            _observable_decimal(features.get(name, "")) for name in feature_names
        )
        if (
            nominal is None
            or step is None
            or current == nominal
            or any(value is None for value in feature_values)
        ):
            return DirectionEvidenceDecision((), "NO_CLEAR_DIRECTION_EVIDENCE")
        current_tick = _tick(current, step, nominal)
        if current_tick is None:
            return DirectionEvidenceDecision((), "CURRENT_VALUE_OFF_GRID")
        item = ParameterDirectionEvidence(
            parameter_name="z_offset",
            current_value=_format_decimal(current),
            current_tick=current_tick,
            nominal_value=_format_decimal(nominal),
            nominal_tick=0,
            recommended_direction="DECREASE" if current > nominal else "INCREASE",
            supporting_features=tuple(
                f"{name}={_format_decimal(value)}"
                for name, value in zip(feature_names, feature_values, strict=True)
            ),
            supporting_rules=(self._rules.z_rule["rule_id"],),
            conflicting_features=(),
            conflict_status="NO_CONFLICT",
            diagnostic_result_version=diagnostic_result_version,
            feature_definition_version=feature_definition_version,
            direction_rule_version=self._rules.direction_rule_version,
            evidence_hash="",
        )
        completed = ParameterDirectionEvidence(
            **{**asdict(item), "evidence_hash": direction_evidence_hash(item)}
        )
        return DirectionEvidenceDecision((completed,), None)


class ParameterPlanGenerator:
    def __init__(
        self,
        validator: ParameterSafetyValidator | None = None,
        planning_policy: ParameterGenerationPolicy | None = None,
    ) -> None:
        self._validator = validator or ParameterSafetyValidator()
        self._planning_policy = planning_policy or DEFAULT_GENERATION_POLICY

    def generate(
        self,
        *,
        root_cause: str,
        parameter_family: str,
        current_values: dict[str, str],
        direction_evidence: tuple[ParameterDirectionEvidence, ...],
        snapshot: ParameterConstraintSnapshot,
        diagnostic_result_version: str,
        case_retrieval_result_version: str | None,
        cases: tuple[HistoricalCaseAction, ...],
        feature_definition_version: str,
        product_model: str,
    ) -> CandidateGenerationDecision:
        usable = tuple(
            item
            for item in direction_evidence
            if item.conflict_status == "NO_CONFLICT" and item.current_tick not in (None, 0)
        )
        if not usable:
            return CandidateGenerationDecision((), (), "NO_COMPATIBLE_APPROVED_CASE")
        raw_candidates: list[ParameterPlanCandidate] = []
        conservative = self._build_candidate(
            generation_type="CONSERVATIVE",
            generation_sources=("RULE_CONSERVATIVE",),
            magnitudes={
                item.parameter_name: self._planning_policy.ticks_for("CONSERVATIVE")
                for item in usable
            },
            root_cause=root_cause,
            parameter_family=parameter_family,
            current_values=current_values,
            evidence=usable,
            supporting_case_ids=(),
            snapshot=snapshot,
            diagnostic_result_version=diagnostic_result_version,
            case_retrieval_result_version=case_retrieval_result_version,
        )
        if conservative is not None:
            raw_candidates.append(conservative)
        standard = self._build_candidate(
            generation_type="STANDARD",
            generation_sources=("RULE_STANDARD",),
            magnitudes={
                item.parameter_name: self._planning_policy.ticks_for("STANDARD")
                for item in usable
            },
            root_cause=root_cause,
            parameter_family=parameter_family,
            current_values=current_values,
            evidence=usable,
            supporting_case_ids=(),
            snapshot=snapshot,
            diagnostic_result_version=diagnostic_result_version,
            case_retrieval_result_version=case_retrieval_result_version,
        )
        if standard is not None:
            raw_candidates.append(standard)

        case_magnitudes: dict[str, int] = {}
        supporting_ids: set[str] = set()
        compatible_cases = self._compatible_cases(
            cases,
            root_cause=root_cause,
            parameter_family=parameter_family,
            feature_definition_version=feature_definition_version,
            product_model=product_model,
            evidence=usable,
            snapshot=snapshot,
        )
        for item in usable:
            values = sorted(
                (abs(case.parameter_delta_ticks[item.parameter_name]), case.case_id)
                for case in compatible_cases
                if item.parameter_name in case.parameter_delta_ticks
                and self._direction_matches(
                    case.parameter_delta_ticks[item.parameter_name],
                    item.recommended_direction,
                )
            )
            if not values:
                continue
            count = len(values)
            if count % 2:
                median = Decimal(values[count // 2][0])
            else:
                median = (Decimal(values[count // 2 - 1][0]) + Decimal(values[count // 2][0])) / 2
            case_magnitudes[item.parameter_name] = int(
                median.to_integral_value(rounding=ROUND_HALF_UP)
            )
            supporting_ids.update(case_id for _magnitude, case_id in values)
        if case_magnitudes:
            case_candidate = self._build_candidate(
                generation_type="CASE_GUIDED",
                generation_sources=("CASE_GUIDED_MEDIAN",),
                magnitudes=case_magnitudes,
                root_cause=root_cause,
                parameter_family=parameter_family,
                current_values=current_values,
                evidence=tuple(
                    item for item in usable if item.parameter_name in case_magnitudes
                ),
                supporting_case_ids=tuple(sorted(supporting_ids)),
                snapshot=snapshot,
                diagnostic_result_version=diagnostic_result_version,
                case_retrieval_result_version=case_retrieval_result_version,
            )
            if case_candidate is not None:
                raw_candidates.append(case_candidate)
        case_status = (
            "COMPATIBLE_APPROVED_CASES_USED"
            if case_magnitudes
            else "NO_COMPATIBLE_APPROVED_CASE"
        )
        deduplicated = self._deduplicate(raw_candidates, snapshot)
        passed = tuple(
            sorted(
                (item for item in deduplicated if item.validation_status == "PASSED"),
                key=self._planning_policy.candidate_sort_key,
            )[: self._planning_policy.maximum_candidate_count]
        )
        rejected = tuple(
            item for item in deduplicated if item.validation_status == "REJECTED"
        )
        return CandidateGenerationDecision(passed, rejected, case_status)

    def _build_candidate(
        self,
        *,
        generation_type: str,
        generation_sources: tuple[str, ...],
        magnitudes: dict[str, int],
        root_cause: str,
        parameter_family: str,
        current_values: dict[str, str],
        evidence: tuple[ParameterDirectionEvidence, ...],
        supporting_case_ids: tuple[str, ...],
        snapshot: ParameterConstraintSnapshot,
        diagnostic_result_version: str,
        case_retrieval_result_version: str | None,
    ) -> ParameterPlanCandidate | None:
        constraints = snapshot.by_name()
        current_ticks: dict[str, int | None] = {}
        proposed_ticks: dict[str, int | None] = {}
        proposed_values = dict(current_values)
        deltas: dict[str, str] = {}
        delta_ticks: dict[str, int | None] = {}
        evidence_by_name = {item.parameter_name: item for item in evidence}
        for name in sorted(current_values):
            constraint = constraints.get(name)
            current = _decimal(current_values[name])
            if constraint is None or current is None:
                return None
            nominal = _decimal(constraint.nominal_value)
            step = _decimal(constraint.step)
            maximum_delta = _decimal(constraint.maximum_single_plan_delta)
            if nominal is None or step is None or maximum_delta is None:
                return None
            current_tick = _tick(current, step, nominal)
            current_ticks[name] = current_tick
            proposed_ticks[name] = current_tick
            if name not in magnitudes or name not in evidence_by_name or current_tick in (None, 0):
                continue
            maximum_ticks = int(maximum_delta / step)
            magnitude = min(magnitudes[name], abs(current_tick), maximum_ticks)
            if magnitude <= 0:
                continue
            direction = 1 if evidence_by_name[name].recommended_direction == "INCREASE" else -1
            proposed_tick = current_tick + direction * magnitude
            proposed = nominal + proposed_tick * step
            proposed_ticks[name] = proposed_tick
            proposed_values[name] = _format_decimal(proposed)
            delta_ticks[name] = direction * magnitude
            deltas[name] = _format_decimal(direction * magnitude * step)
        if not delta_ticks:
            return None
        candidate = ParameterPlanCandidate(
            candidate_id="",
            generation_type=generation_type,
            generation_sources=generation_sources,
            root_cause=root_cause,
            parameter_family=parameter_family,
            current_values={name: _format_decimal(_decimal(value)) for name, value in sorted(current_values.items())},
            proposed_values={name: proposed_values[name] for name in sorted(proposed_values)},
            current_ticks={name: current_ticks[name] for name in sorted(current_ticks)},
            proposed_ticks={name: proposed_ticks[name] for name in sorted(proposed_ticks)},
            deltas={name: deltas[name] for name in sorted(deltas)},
            delta_ticks={name: delta_ticks[name] for name in sorted(delta_ticks)},
            total_absolute_delta_ticks=sum(abs(value) for value in delta_ticks.values() if value is not None),
            direction_evidence=tuple(sorted(evidence, key=lambda item: item.parameter_name)),
            supporting_case_ids=tuple(sorted(supporting_case_ids)),
            supporting_case_count=len(set(supporting_case_ids)),
            constraint_snapshot_version=snapshot.snapshot_version,
            rule_set_version=snapshot.rule_set_version,
            direction_rule_version=DIRECTION_RULE_VERSION,
            safety_rule_version=self._validator.safety_rule_version,
            diagnostic_result_version=diagnostic_result_version,
            case_retrieval_result_version=case_retrieval_result_version,
            validation_checks=(),
            validation_status="REJECTED",
            rejection_reasons=(),
            candidate_hash="",
        )
        candidate_hash = candidate_content_hash(candidate)
        candidate = replace(
            candidate,
            candidate_id=f"tw-parameter-candidate-{candidate_hash[:16]}",
            candidate_hash=candidate_hash,
        )
        return self._validated(candidate, snapshot)

    def _validated(
        self,
        candidate: ParameterPlanCandidate,
        snapshot: ParameterConstraintSnapshot,
    ) -> ParameterPlanCandidate:
        validation = self._validator.validate(
            candidate,
            snapshot=snapshot,
            versions=SafetyVersionContext(
                constraint_snapshot_version=snapshot.snapshot_version,
                rule_set_version=snapshot.rule_set_version,
                direction_rule_version=DIRECTION_RULE_VERSION,
                safety_rule_version=self._validator.safety_rule_version,
                diagnostic_result_version=candidate.diagnostic_result_version,
                case_retrieval_result_version=candidate.case_retrieval_result_version,
            ),
        )
        return replace(
            candidate,
            validation_checks=validation.validation_checks,
            validation_status=validation.validation_status,
            rejection_reasons=validation.rejection_reasons,
        )

    def _compatible_cases(
        self,
        cases: tuple[HistoricalCaseAction, ...],
        *,
        root_cause: str,
        parameter_family: str,
        feature_definition_version: str,
        product_model: str,
        evidence: tuple[ParameterDirectionEvidence, ...],
        snapshot: ParameterConstraintSnapshot,
    ) -> tuple[HistoricalCaseAction, ...]:
        evidence_names = {item.parameter_name for item in evidence}
        evidence_directions = {
            item.parameter_name: item.recommended_direction for item in evidence
        }
        return tuple(
            case
            for case in sorted(cases, key=lambda item: item.case_id)
            if case.status == "APPROVED"
            and case.source_partition == "TRAIN"
            and case.source_partition_id == "diagnostic-dev-train-v1"
            and case.station_type == "AA"
            and case.product_model == product_model
            and case.reviewed_root_cause == root_cause
            and case.parameter_family == parameter_family
            and case.action_version == self._planning_policy.case_action_version
            and case.historical_safety_status == "PASSED"
            and case.historical_safety_rule_version
            == self._validator.safety_rule_version
            and case.historical_simulated_result_status == "SUCCESS"
            and case.center_within_tolerance
            and case.feature_definition_version == feature_definition_version
            and case.rule_set_version == snapshot.rule_set_version
            and case.retrieval_rule_version == "tw-case-retrieval-rules-v1"
            and case.case_schema_version == "tw-approved-case-schema-v1"
            and bool(set(case.parameter_delta_ticks) & evidence_names)
            and self._validator.historical_action_is_safe(
                case.parameter_delta_ticks,
                parameter_family=case.parameter_family,
                snapshot=snapshot,
            )
            and all(
                name not in evidence_directions
                or self._direction_matches(value, evidence_directions[name])
                for name, value in case.parameter_delta_ticks.items()
            )
        )

    def _deduplicate(
        self,
        candidates: list[ParameterPlanCandidate],
        snapshot: ParameterConstraintSnapshot,
    ) -> tuple[ParameterPlanCandidate, ...]:
        by_values: dict[tuple[tuple[str, str], ...], ParameterPlanCandidate] = {}
        priority = {"CONSERVATIVE": 0, "STANDARD": 1, "CASE_GUIDED": 2}
        for candidate in candidates:
            key = tuple(sorted(candidate.proposed_values.items()))
            current = by_values.get(key)
            if current is None:
                by_values[key] = candidate
                continue
            preferred, other = sorted(
                (current, candidate), key=lambda item: priority[item.generation_type]
            )
            merged = replace(
                preferred,
                generation_sources=tuple(sorted(set(preferred.generation_sources + other.generation_sources))),
                supporting_case_ids=tuple(sorted(set(preferred.supporting_case_ids + other.supporting_case_ids))),
                supporting_case_count=len(set(preferred.supporting_case_ids + other.supporting_case_ids)),
                validation_checks=(),
                validation_status="REJECTED",
                rejection_reasons=(),
                candidate_hash="",
                candidate_id="",
            )
            merged_hash = candidate_content_hash(merged)
            merged = replace(
                merged,
                candidate_id=f"tw-parameter-candidate-{merged_hash[:16]}",
                candidate_hash=merged_hash,
            )
            by_values[key] = self._validated(merged, snapshot)
        return tuple(by_values.values())

    @staticmethod
    def _direction_matches(delta_ticks: int, direction: str) -> bool:
        return (delta_ticks > 0 and direction == "INCREASE") or (
            delta_ticks < 0 and direction == "DECREASE"
        )


class ParameterSafetyValidator:
    def __init__(self, policy: ParameterSafetyPolicy | None = None) -> None:
        self._policy = policy or DEFAULT_SAFETY_POLICY

    @property
    def safety_rule_version(self) -> str:
        return self._policy.safety_rule_version

    def historical_action_is_safe(
        self,
        delta_ticks: dict[str, int],
        *,
        parameter_family: str,
        snapshot: ParameterConstraintSnapshot,
    ) -> bool:
        constraints = snapshot.by_name()
        names = set(delta_ticks)
        if (
            not names
            or len(names) > self._policy.maximum_adjusted_parameter_count
            or not names.issubset(
                self._policy.parameters_for_family(parameter_family)
            )
            or not names.issubset(constraints)
        ):
            return False
        for name, value in delta_ticks.items():
            constraint = constraints[name]
            step = _decimal(constraint.step)
            maximum_delta = _decimal(constraint.maximum_single_plan_delta)
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value == 0
                or step is None
                or maximum_delta is None
                or step <= 0
                or abs(value) > int(maximum_delta / step)
            ):
                return False
        return True

    def validate(
        self,
        candidate: ParameterPlanCandidate,
        *,
        snapshot: ParameterConstraintSnapshot,
        versions: SafetyVersionContext,
    ) -> SafetyValidationResult:
        checks: list[ValidationCheck] = []
        reasons: list[str] = []
        constraints = snapshot.by_name()
        expected_names = set(constraints)
        value_names_valid = (
            set(candidate.current_values)
            == set(candidate.proposed_values)
            == expected_names
        )
        self._check(
            checks,
            reasons,
            "AUTHORIZED_PARAMETERS",
            value_names_valid,
            "候选只包含约束快照授权参数。",
            "候选包含缺失或未授权参数。",
            "UNAUTHORIZED_PARAMETER",
        )
        parsed: dict[str, tuple[Decimal, Decimal, Decimal, Decimal, Decimal, Decimal]] = {}
        numeric_valid = value_names_valid
        if numeric_valid:
            for name in sorted(expected_names):
                constraint = constraints[name]
                values = tuple(
                    _decimal(value)
                    for value in (
                        candidate.current_values[name],
                        candidate.proposed_values[name],
                        constraint.nominal_value,
                        constraint.minimum,
                        constraint.maximum,
                        constraint.step,
                    )
                )
                maximum_delta = _decimal(constraint.maximum_single_plan_delta)
                if any(value is None for value in values) or maximum_delta is None:
                    numeric_valid = False
                    break
                current, proposed, nominal, minimum, maximum, step = values
                if step <= 0 or minimum > nominal or nominal > maximum or maximum_delta < 0:
                    numeric_valid = False
                    break
                parsed[name] = (current, proposed, nominal, minimum, maximum, step)
        self._check(
            checks,
            reasons,
            "NUMERIC_PRECISION",
            numeric_valid,
            "候选与快照数值均可无损转换为固定精度 Decimal。",
            "候选或快照包含无效精度数值。",
            "PARAMETER_NUMERIC_INVALID",
        )
        if numeric_valid:
            current_range = all(
                minimum <= current <= maximum
                for current, _proposed, _nominal, minimum, maximum, _step in parsed.values()
            )
            proposed_range = all(
                minimum <= proposed <= maximum
                for _current, proposed, _nominal, minimum, maximum, _step in parsed.values()
            )
            current_grid = all(
                _tick(current, step, nominal) is not None
                for current, _proposed, nominal, _minimum, _maximum, step in parsed.values()
            )
            proposed_grid = all(
                _tick(proposed, step, nominal) is not None
                for _current, proposed, nominal, _minimum, _maximum, step in parsed.values()
            )
        else:
            current_range = proposed_range = current_grid = proposed_grid = False
        self._check(checks, reasons, "CURRENT_VALUE_RANGE", current_range, "当前值均在合法范围内。", "当前值超出合法范围。", "CURRENT_VALUE_OUT_OF_RANGE")
        self._check(checks, reasons, "CURRENT_VALUE_GRID", current_grid, "当前值均位于任务约束快照的步长网格。", "当前值不在任务约束快照的步长网格，未执行取整。", "CURRENT_VALUE_OFF_GRID")
        self._check(checks, reasons, "PROPOSED_VALUE_RANGE", proposed_range, "建议值均在合法范围内。", "建议值超出合法范围。", "PROPOSED_VALUE_OUT_OF_RANGE")
        self._check(checks, reasons, "PROPOSED_VALUE_GRID", proposed_grid, "建议值均位于任务约束快照的步长网格。", "建议值不在任务约束快照的步长网格。", "PROPOSED_VALUE_OFF_GRID")

        changed = tuple(
            name
            for name in sorted(parsed)
            if parsed[name][0] != parsed[name][1]
        )
        self._check(checks, reasons, "NON_ZERO_DELTA", bool(changed), "候选至少调整一个参数。", "候选所有 delta 均为零。", "ZERO_DELTA_CANDIDATE")
        self._check(
            checks,
            reasons,
            "PARAMETER_COUNT_LIMIT",
            0 < len(changed) <= self._policy.maximum_adjusted_parameter_count,
            "候选调整参数数量不超过版本化安全规则上限。",
            "候选调整参数数量超过版本化安全规则上限。",
            "PARAMETER_COUNT_EXCEEDED",
        )
        changed_families = {
            self._policy.family_for_parameter(name) for name in changed
        }
        single_family = len(changed_families) == 1 and candidate.parameter_family in changed_families
        self._check(checks, reasons, "SINGLE_PARAMETER_FAMILY", single_family, "候选只调整一个参数族。", "候选混合参数族或参数族标记不一致。", "MIXED_PARAMETER_FAMILY")
        allowed_family = self._policy.family_for_root_cause(candidate.root_cause)
        top1_allowed = (
            allowed_family is not None
            and candidate.parameter_family == allowed_family
            and set(changed).issubset(
                self._policy.parameters_for_family(allowed_family)
            )
        )
        self._check(checks, reasons, "TOP1_ALLOWED_FAMILY", top1_allowed, "调整参数属于 Top-1 允许参数族。", "调整参数不属于 Top-1 允许参数族。", "PARAMETER_NOT_ALLOWED_FOR_TOP1")

        evidence_by_name = {item.parameter_name: item for item in candidate.direction_evidence}
        evidence_present = all(name in evidence_by_name for name in changed)
        evidence_conflict = any(
            evidence_by_name[name].conflict_status != "NO_CONFLICT"
            for name in changed
            if name in evidence_by_name
        )
        evidence_integrity = evidence_present and numeric_valid and current_grid
        for name in changed:
            evidence = evidence_by_name.get(name)
            if evidence is None or name not in parsed:
                evidence_integrity = False
                continue
            current, _proposed, nominal, _minimum, _maximum, step = parsed[name]
            expected_direction = "DECREASE" if current > nominal else "INCREASE"
            evidence_integrity = evidence_integrity and (
                _decimal(evidence.current_value) == current
                and evidence.current_tick == _tick(current, step, nominal)
                and _decimal(evidence.nominal_value) == nominal
                and evidence.nominal_tick == 0
                and evidence.recommended_direction == expected_direction
                and bool(evidence.supporting_features)
                and bool(evidence.supporting_rules)
                and not evidence.conflicting_features
                and evidence.diagnostic_result_version
                == candidate.diagnostic_result_version
                and evidence.feature_definition_version
                == "tw-feature-definition-v1"
                and evidence.direction_rule_version
                == candidate.direction_rule_version
                and evidence.evidence_hash == direction_evidence_hash(evidence)
            )
        self._check(checks, reasons, "DIRECTION_EVIDENCE_PRESENT", evidence_present, "每个调整参数均绑定方向证据。", "调整参数缺少方向证据。", "DIRECTION_EVIDENCE_MISSING")
        self._check(checks, reasons, "DIRECTION_EVIDENCE_CONFLICT", not evidence_conflict, "方向证据无冲突。", "方向证据存在冲突。", "DIRECTION_EVIDENCE_CONFLICT")
        self._check(checks, reasons, "DIRECTION_EVIDENCE_INTEGRITY", evidence_integrity, "方向证据与当前值、标称值、版本及证据哈希一致。", "方向证据与当前候选、版本或证据哈希不一致。", "DIRECTION_EVIDENCE_INVALID")

        reduced = bool(changed)
        not_crossed = bool(changed)
        direction_matches = bool(changed)
        maximum_delta_valid = bool(changed)
        tick_fields_valid = numeric_valid and current_grid and proposed_grid
        delta_fields_valid = numeric_valid and set(candidate.deltas) == set(changed) and set(candidate.delta_ticks) == set(changed)
        if tick_fields_valid:
            for name, (current, proposed, nominal, _minimum, _maximum, step) in parsed.items():
                current_tick = _tick(current, step, nominal)
                proposed_tick = _tick(proposed, step, nominal)
                tick_fields_valid = tick_fields_valid and (
                    candidate.current_ticks.get(name) == current_tick
                    and candidate.proposed_ticks.get(name) == proposed_tick
                )
        else:
            delta_fields_valid = False
        for name in changed:
            current, proposed, nominal, _minimum, _maximum, step = parsed[name]
            reduced = reduced and abs(proposed - nominal) < abs(current - nominal)
            not_crossed = not_crossed and (
                proposed == nominal or (current - nominal) * (proposed - nominal) > 0
            )
            delta = proposed - current
            evidence = evidence_by_name.get(name)
            direction_matches = direction_matches and evidence is not None and (
                (delta > 0 and evidence.recommended_direction == "INCREASE")
                or (delta < 0 and evidence.recommended_direction == "DECREASE")
            )
            maximum_delta = _decimal(constraints[name].maximum_single_plan_delta)
            maximum_delta_valid = maximum_delta_valid and maximum_delta is not None and abs(delta) <= maximum_delta
            current_tick = _tick(current, step, nominal)
            proposed_tick = _tick(proposed, step, nominal)
            tick_fields_valid = tick_fields_valid and (
                candidate.delta_ticks.get(name) == proposed_tick - current_tick
            )
            delta_fields_valid = delta_fields_valid and (
                candidate.delta_ticks.get(name) == proposed_tick - current_tick
                and _decimal(candidate.deltas.get(name, "")) == proposed - current
            )
        expected_total = sum(abs(candidate.delta_ticks.get(name) or 0) for name in changed)
        tick_fields_valid = tick_fields_valid and candidate.total_absolute_delta_ticks == expected_total
        self._check(checks, reasons, "DIRECTION_MATCH", direction_matches, "调整方向与当前方向证据一致。", "调整方向与当前方向证据不一致。", "DIRECTION_MISMATCH")
        self._check(checks, reasons, "NOMINAL_DEVIATION_REDUCED", reduced, "每项调整均缩小相对标称值偏差。", "调整未缩小相对标称值偏差。", "NOMINAL_DEVIATION_NOT_REDUCED")
        self._check(checks, reasons, "NOMINAL_NOT_CROSSED", not_crossed, "调整未跨过标称值。", "调整跨过标称值。", "NOMINAL_VALUE_CROSSED")
        self._check(checks, reasons, "MAXIMUM_SINGLE_PLAN_DELTA", maximum_delta_valid, "单次变化未超过约束快照上限。", "单次变化超过约束快照上限。", "MAXIMUM_SINGLE_PLAN_DELTA_EXCEEDED")
        self._check(checks, reasons, "TICK_FIELDS", tick_fields_valid, "tick 与 Decimal 候选内容一致。", "tick 与 Decimal 候选内容不一致。", "CANDIDATE_TICK_MISMATCH")
        self._check(checks, reasons, "DELTA_FIELDS", delta_fields_valid, "delta 与当前值、建议值和 tick 一致。", "delta 与当前值、建议值或 tick 不一致。", "CANDIDATE_DELTA_MISMATCH")

        version_valid = (
            snapshot.snapshot_version == versions.constraint_snapshot_version == candidate.constraint_snapshot_version
            and snapshot.rule_set_version == versions.rule_set_version == candidate.rule_set_version
            and versions.direction_rule_version == candidate.direction_rule_version == DIRECTION_RULE_VERSION
            and versions.safety_rule_version
            == candidate.safety_rule_version
            == self._policy.safety_rule_version
            and versions.diagnostic_result_version == candidate.diagnostic_result_version
            and versions.case_retrieval_result_version == candidate.case_retrieval_result_version
        )
        self._check(checks, reasons, "VERSION_BINDINGS", version_valid, "候选、诊断、规则、快照和案例版本均为当前版本。", "候选版本绑定已失效。", "CANDIDATE_VERSION_STALE")
        expected_hash = candidate_content_hash(candidate)
        hash_passed = candidate.candidate_hash == expected_hash
        self._check(checks, reasons, "CANDIDATE_HASH", hash_passed, "候选规范化内容哈希匹配。", "候选规范化内容哈希不匹配。", "CANDIDATE_HASH_MISMATCH")
        return SafetyValidationResult(
            validation_status="PASSED" if not reasons else "REJECTED",
            validation_checks=tuple(checks),
            rejection_reasons=tuple(reasons),
            safety_rule_version=self._policy.safety_rule_version,
            constraint_snapshot_version=snapshot.snapshot_version,
            validated_candidate_hash=candidate.candidate_hash,
        )

    @staticmethod
    def _check(
        checks: list[ValidationCheck],
        reasons: list[str],
        code: str,
        passed: bool,
        passed_detail: str,
        failed_detail: str,
        rejection_reason: str,
    ) -> None:
        checks.append(
            ValidationCheck(
                check_code=code,
                status="PASSED" if passed else "FAILED",
                detail=passed_detail if passed else failed_detail,
            )
        )
        if not passed and rejection_reason not in reasons:
            reasons.append(rejection_reason)
