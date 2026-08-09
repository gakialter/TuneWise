from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, replace
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping

from .detection import (
    AnomalyDetector,
    AnomalyResult,
    ControlLimitRegistry,
    ControlLimitSnapshot,
    DetectionGuardError,
    DetectionInput,
    SpcRuleSnapshot,
    SpcRuleRegistry,
    canonical_measurement_hash,
)
from .diagnosis import (
    DiagnosticAssetError,
    DiagnosticAssetLoader,
    DiagnosticGuardError,
    FeatureEngineer,
    FeatureEngineeringError,
    RootCauseDiagnoser,
)
from .diagnostic_contract import DIAGNOSTIC_RESULT_VERSION, PARAMETER_FIELDS
from .importing import CANONICAL_PRECISION
from .parameter_planning import (
    DirectionEvidenceGenerator,
    ParameterConstraint,
    ParameterConstraintSnapshot,
    ParameterPlanGenerator,
    ParameterPlanningAssetError,
    ParameterPlanningAssetLoader,
    ParameterSafetyValidator,
    validate_current_parameter_values,
)
from .shadow_data import (
    ImportedShadowDataset,
    SHADOW_STORAGE_PARTITION,
    ShadowDataQualityReport,
    ShadowDataStatus,
    ShadowEvaluationReport,
    ShadowPrediction,
    evaluate_shadow_dataset,
    rebuild_shadow_quality_report,
    validate_shadow_evidence_bundle,
)


SHADOW_ANALYSIS_CONTRACT_VERSION = "tw-shadow-analysis-contract-v1"
SHADOW_ANALYSIS_VERSION = "tw-shadow-analysis-v1"
SHADOW_ANALYSIS_RESULT_VERSION = "tw-shadow-analysis-result-v1"
SHADOW_ANALYSIS_CANONICALIZER_VERSION = "tw-shadow-analysis-canonical-json-v1"
SHADOW_CASE_LIBRARY_MODE = "DISABLED_SHADOW_ISOLATION"
SHADOW_ANALYSIS_DISCLAIMER = (
    "影子分析仅产生离线模型输出和规则检查，不代表参数有效、真实设备安全或真实产线收益。"
)
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


class ShadowAnalysisError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class ShadowAnalysisContract:
    contract_version: str
    analysis_version: str
    mapping_version: str
    raw_file_sha256: str
    canonical_schema_version: str
    canonicalizer_version: str
    canonical_observation_sha256: str
    input_data_version: str
    product_model: str
    rule_set_version: str
    control_limits: ControlLimitSnapshot
    spc_rules: SpcRuleSnapshot
    parameter_constraints: ParameterConstraintSnapshot
    parameter_constraint_snapshot_sha256: str
    diagnostic_asset_manifest_sha256: str
    planning_asset_manifest_sha256: str
    model_version: str
    preprocessing_version: str
    feature_definition_version: str
    safety_rule_version: str
    case_library_mode: str

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> ShadowAnalysisContract:
        expected_keys = {
            "contract_version",
            "analysis_version",
            "mapping_version",
            "raw_file_sha256",
            "canonical_schema_version",
            "canonicalizer_version",
            "canonical_observation_sha256",
            "input_data_version",
            "product_model",
            "rule_set_version",
            "control_limits",
            "spc_rules",
            "parameter_constraints",
            "parameter_constraint_snapshot_sha256",
            "diagnostic_asset_manifest_sha256",
            "planning_asset_manifest_sha256",
            "model_version",
            "preprocessing_version",
            "feature_definition_version",
            "safety_rule_version",
            "case_library_mode",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected_keys:
            raise ShadowAnalysisError(
                "ANALYSIS_CONTRACT_INVALID",
                "影子分析契约字段不完整或包含未定义字段。",
            )
        if payload["contract_version"] != SHADOW_ANALYSIS_CONTRACT_VERSION:
            raise ShadowAnalysisError(
                "ANALYSIS_CONTRACT_INVALID", "影子分析契约版本不受支持。"
            )
        if payload["analysis_version"] != SHADOW_ANALYSIS_VERSION:
            raise ShadowAnalysisError(
                "ANALYSIS_CONTRACT_INVALID", "影子分析实现版本不受支持。"
            )
        text_fields = (
            "mapping_version",
            "canonical_schema_version",
            "canonicalizer_version",
            "input_data_version",
            "product_model",
            "rule_set_version",
            "model_version",
            "preprocessing_version",
            "feature_definition_version",
            "safety_rule_version",
        )
        values = {field: _required_text(payload[field], field) for field in text_fields}
        canonical_hash = _required_sha256(
            payload["canonical_observation_sha256"],
            "canonical_observation_sha256",
        )
        raw_hash = _required_sha256(payload["raw_file_sha256"], "raw_file_sha256")
        parameter_hash = _required_sha256(
            payload["parameter_constraint_snapshot_sha256"],
            "parameter_constraint_snapshot_sha256",
        )
        diagnostic_hash = _required_sha256(
            payload["diagnostic_asset_manifest_sha256"],
            "diagnostic_asset_manifest_sha256",
        )
        planning_hash = _required_sha256(
            payload["planning_asset_manifest_sha256"],
            "planning_asset_manifest_sha256",
        )
        if payload["case_library_mode"] != SHADOW_CASE_LIBRARY_MODE:
            raise ShadowAnalysisError(
                "ANALYSIS_CONTRACT_INVALID",
                "影子分析必须显式关闭案例库检索并保持只读隔离。",
            )
        control_limits = _parse_control_limits(payload["control_limits"])
        spc_rules = _parse_spc_rules(payload["spc_rules"])
        parameter_constraints = _parse_parameter_constraints(
            payload["parameter_constraints"]
        )
        if (
            control_limits.rule_set_version != values["rule_set_version"]
            or spc_rules.rule_set_version != values["rule_set_version"]
            or parameter_constraints.rule_set_version != values["rule_set_version"]
            or parameter_constraints.product_model != values["product_model"]
        ):
            raise ShadowAnalysisError(
                "ANALYSIS_CONTRACT_INVALID",
                "控制限、SPC、参数约束与分析契约版本绑定不一致。",
            )
        actual_parameter_hash = _parameter_snapshot_hash(parameter_constraints)
        if actual_parameter_hash != parameter_hash:
            raise ShadowAnalysisError(
                "ANALYSIS_CONTRACT_INVALID",
                "参数约束快照哈希与分析契约不一致。",
            )
        return cls(
            contract_version=SHADOW_ANALYSIS_CONTRACT_VERSION,
            analysis_version=SHADOW_ANALYSIS_VERSION,
            mapping_version=values["mapping_version"],
            raw_file_sha256=raw_hash,
            canonical_schema_version=values["canonical_schema_version"],
            canonicalizer_version=values["canonicalizer_version"],
            canonical_observation_sha256=canonical_hash,
            input_data_version=values["input_data_version"],
            product_model=values["product_model"],
            rule_set_version=values["rule_set_version"],
            control_limits=control_limits,
            spc_rules=spc_rules,
            parameter_constraints=parameter_constraints,
            parameter_constraint_snapshot_sha256=parameter_hash,
            diagnostic_asset_manifest_sha256=diagnostic_hash,
            planning_asset_manifest_sha256=planning_hash,
            model_version=values["model_version"],
            preprocessing_version=values["preprocessing_version"],
            feature_definition_version=values["feature_definition_version"],
            safety_rule_version=values["safety_rule_version"],
            case_library_mode=SHADOW_CASE_LIBRARY_MODE,
        )

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "analysis_version": self.analysis_version,
            "mapping_version": self.mapping_version,
            "raw_file_sha256": self.raw_file_sha256,
            "canonical_schema_version": self.canonical_schema_version,
            "canonicalizer_version": self.canonicalizer_version,
            "canonical_observation_sha256": self.canonical_observation_sha256,
            "input_data_version": self.input_data_version,
            "product_model": self.product_model,
            "rule_set_version": self.rule_set_version,
            "control_limits": _control_limit_payload(self.control_limits),
            "spc_rules": _spc_rule_payload(self.spc_rules),
            "parameter_constraints": _parameter_snapshot_payload(
                self.parameter_constraints
            ),
            "parameter_constraint_snapshot_sha256": (
                self.parameter_constraint_snapshot_sha256
            ),
            "diagnostic_asset_manifest_sha256": (
                self.diagnostic_asset_manifest_sha256
            ),
            "planning_asset_manifest_sha256": self.planning_asset_manifest_sha256,
            "model_version": self.model_version,
            "preprocessing_version": self.preprocessing_version,
            "feature_definition_version": self.feature_definition_version,
            "safety_rule_version": self.safety_rule_version,
            "case_library_mode": self.case_library_mode,
        }

    @property
    def contract_hash(self) -> str:
        return _canonical_hash(self.canonical_payload())


@dataclass(frozen=True, slots=True)
class ShadowAnalysisQualification:
    eligible: bool
    code: str
    message: str
    mapping_version: str
    canonical_observation_sha256: str
    analysis_contract_hash: str
    rule_set_version: str
    control_limit_snapshot_version: str
    spc_rule_snapshot_version: str
    model_version: str
    safety_rule_version: str
    analysis_group_count: int
    diagnostic_eligible_group_count: int
    safety_eligible_group_count: int
    insufficient_group_count: int
    diagnostic_runnable: bool
    safety_recommendation_runnable: bool


@dataclass(frozen=True, slots=True)
class ShadowSafetyCandidate:
    candidate_id: str
    generation_type: str
    root_cause: str
    parameter_family: str
    changed_parameters: tuple[str, ...]
    proposed_values: tuple[tuple[str, str], ...]
    delta_ticks: tuple[tuple[str, int], ...]
    validation_status: str
    safety_rule_version: str
    constraint_snapshot_version: str
    candidate_hash: str


@dataclass(frozen=True, slots=True)
class ShadowGroupAnalysis:
    batch_id: str | None
    lot_id: str | None
    sample_count: int
    measurement_hash: str
    detection_status: str
    predicted_anomaly: str | None
    detection_result_hash: str
    diagnostic_status: str
    ranked_root_causes: tuple[str, ...]
    diagnostic_feature_hash: str | None
    safety_candidate_status: str
    predicted_parameter_direction: str | None
    safety_candidates: tuple[ShadowSafetyCandidate, ...]
    refusal_code: str | None

    def evaluation_prediction(self) -> ShadowPrediction:
        return ShadowPrediction(
            batch_id=self.batch_id,
            lot_id=self.lot_id,
            detection_status=self.detection_status,
            predicted_anomaly=self.predicted_anomaly,
            ranked_root_causes=self.ranked_root_causes,
            safety_candidate_status=self.safety_candidate_status,
            predicted_parameter_direction=self.predicted_parameter_direction,
        )


@dataclass(frozen=True, slots=True)
class ShadowAnalysisResult:
    analysis_result_version: str
    analysis_canonicalizer_version: str
    analysis_result_id: str
    analysis_result_hash: str
    source_type: str
    source_metadata: tuple[tuple[str, str], ...]
    source_authenticity_status: str
    mapping_version: str
    raw_file_sha256: str
    canonical_schema_version: str
    canonicalizer_version: str
    canonical_observation_sha256: str
    evidence_bundle_hash: str
    analysis_contract_hash: str
    input_data_version: str
    rule_set_version: str
    control_limit_snapshot_version: str
    spc_rule_snapshot_version: str
    diagnostic_asset_manifest_sha256: str
    planning_asset_manifest_sha256: str
    model_version: str
    preprocessing_version: str
    feature_definition_version: str
    safety_rule_version: str
    parameter_constraint_snapshot_sha256: str
    case_library_mode: str
    storage_partition: str
    eligible_for_training: bool
    eligible_for_approved_case_library: bool
    automatic_retraining_allowed: bool
    fixed_demo_asset_mutation_allowed: bool
    quality_report: ShadowDataQualityReport
    qualification: ShadowAnalysisQualification
    group_results: tuple[ShadowGroupAnalysis, ...]
    evaluation: ShadowEvaluationReport
    disclaimer: str


class ShadowAnalysisRunner:
    def __init__(
        self,
        *,
        diagnostic_asset_root: Path,
        planning_asset_root: Path,
    ) -> None:
        self._diagnostic_asset_root = diagnostic_asset_root.resolve()
        self._planning_asset_root = planning_asset_root.resolve()

    def qualify(
        self,
        dataset: ImportedShadowDataset,
        contract: ShadowAnalysisContract,
    ) -> ShadowAnalysisQualification:
        self._validate_data_binding(dataset, contract)
        self._load_assets(contract)
        return self._qualification(dataset, contract, self._groups(dataset))

    @staticmethod
    def _qualification(
        dataset: ImportedShadowDataset,
        contract: ShadowAnalysisContract,
        groups: tuple[
            tuple[str | None, str | None, tuple[dict[str, str], ...]], ...
        ],
    ) -> ShadowAnalysisQualification:
        diagnostic_eligible = sum(
            len(measurements) >= contract.spc_rules.minimum_sample_count
            for _batch_id, _lot_id, measurements in groups
        )
        safety_eligible = sum(
            len(measurements) >= contract.spc_rules.minimum_sample_count
            and _parameter_state_ready(
                measurements,
                contract.parameter_constraints,
            )
            for _batch_id, _lot_id, measurements in groups
        )
        insufficient = len(groups) - diagnostic_eligible
        code = "ELIGIBLE" if diagnostic_eligible else "NO_DIAGNOSTIC_GROUP_READY"
        message = (
            "数据、分析契约和冻结资产绑定校验通过。"
            if diagnostic_eligible
            else "契约绑定通过，但所有 group 均低于 SPC 最小样本条件。"
        )
        return ShadowAnalysisQualification(
            eligible=True,
            code=code,
            message=message,
            mapping_version=dataset.mapping_version,
            canonical_observation_sha256=dataset.canonical_observation_sha256,
            analysis_contract_hash=contract.contract_hash,
            rule_set_version=contract.rule_set_version,
            control_limit_snapshot_version=contract.control_limits.snapshot_version,
            spc_rule_snapshot_version=contract.spc_rules.snapshot_version,
            model_version=contract.model_version,
            safety_rule_version=contract.safety_rule_version,
            analysis_group_count=len(groups),
            diagnostic_eligible_group_count=diagnostic_eligible,
            safety_eligible_group_count=safety_eligible,
            insufficient_group_count=insufficient,
            diagnostic_runnable=diagnostic_eligible > 0,
            safety_recommendation_runnable=safety_eligible > 0,
        )

    def run(
        self,
        dataset: ImportedShadowDataset,
        contract: ShadowAnalysisContract,
    ) -> ShadowAnalysisResult:
        self._validate_data_binding(dataset, contract)
        diagnostic_assets, planning_assets = self._load_assets(contract)
        groups = self._groups(dataset)
        qualification = self._qualification(dataset, contract, groups)
        group_results = tuple(
            self._analyze_group(
                dataset,
                contract,
                batch_id=batch_id,
                lot_id=lot_id,
                measurements=measurements,
                diagnostic_assets=diagnostic_assets,
                planning_assets=planning_assets,
            )
            for batch_id, lot_id, measurements in groups
        )
        evaluation = evaluate_shadow_dataset(
            dataset,
            tuple(result.evaluation_prediction() for result in group_results),
        )
        rebuilt_quality_report = rebuild_shadow_quality_report(dataset)
        qualified_quality_report = replace(
            rebuilt_quality_report,
            analysis_contract_bound=True,
            diagnostic_runnable=qualification.diagnostic_runnable,
            safety_recommendation_runnable=(
                qualification.safety_recommendation_runnable
            ),
            messages=tuple(
                message
                for message in rebuilt_quality_report.messages
                if not message.startswith("尚未绑定版本化分析契约")
            )
            + (qualification.message,),
        )
        base = ShadowAnalysisResult(
            analysis_result_version=SHADOW_ANALYSIS_RESULT_VERSION,
            analysis_canonicalizer_version=SHADOW_ANALYSIS_CANONICALIZER_VERSION,
            analysis_result_id="",
            analysis_result_hash="",
            source_type=dataset.source_type.value,
            source_metadata=dataset.source_metadata,
            source_authenticity_status=dataset.source_authenticity_status,
            mapping_version=dataset.mapping_version,
            raw_file_sha256=dataset.raw_file_sha256,
            canonical_schema_version=dataset.canonical_schema_version,
            canonicalizer_version=dataset.canonicalizer_version,
            canonical_observation_sha256=dataset.canonical_observation_sha256,
            evidence_bundle_hash=dataset.evidence_bundle_hash,
            analysis_contract_hash=contract.contract_hash,
            input_data_version=contract.input_data_version,
            rule_set_version=contract.rule_set_version,
            control_limit_snapshot_version=contract.control_limits.snapshot_version,
            spc_rule_snapshot_version=contract.spc_rules.snapshot_version,
            diagnostic_asset_manifest_sha256=(
                contract.diagnostic_asset_manifest_sha256
            ),
            planning_asset_manifest_sha256=contract.planning_asset_manifest_sha256,
            model_version=contract.model_version,
            preprocessing_version=contract.preprocessing_version,
            feature_definition_version=contract.feature_definition_version,
            safety_rule_version=contract.safety_rule_version,
            parameter_constraint_snapshot_sha256=(
                contract.parameter_constraint_snapshot_sha256
            ),
            case_library_mode=contract.case_library_mode,
            storage_partition=dataset.storage_partition,
            eligible_for_training=dataset.eligible_for_training,
            eligible_for_approved_case_library=(
                dataset.eligible_for_approved_case_library
            ),
            automatic_retraining_allowed=dataset.automatic_retraining_allowed,
            fixed_demo_asset_mutation_allowed=(
                dataset.fixed_demo_asset_mutation_allowed
            ),
            quality_report=qualified_quality_report,
            qualification=qualification,
            group_results=group_results,
            evaluation=evaluation,
            disclaimer=SHADOW_ANALYSIS_DISCLAIMER,
        )
        result_hash = shadow_analysis_result_hash(base)
        return replace(
            base,
            analysis_result_id=f"tw-shadow-analysis-{result_hash[:16]}",
            analysis_result_hash=result_hash,
        )

    def _validate_data_binding(
        self,
        dataset: ImportedShadowDataset,
        contract: ShadowAnalysisContract,
    ) -> None:
        try:
            validate_shadow_evidence_bundle(dataset)
            report = rebuild_shadow_quality_report(dataset)
        except ValueError as error:
            raise ShadowAnalysisError(
                "ANALYSIS_EVIDENCE_BUNDLE_MISMATCH",
                str(error),
            ) from error
        try:
            actual_measurement_hash = canonical_measurement_hash(
                tuple(dict(measurement) for measurement in dataset.measurements)
            )
        except DetectionGuardError as error:
            raise ShadowAnalysisError(
                "ANALYSIS_DATA_INTEGRITY_INVALID", error.message
            ) from error
        if (
            dataset.mapping_version != contract.mapping_version
            or dataset.raw_file_sha256 != contract.raw_file_sha256
            or dataset.canonical_schema_version != contract.canonical_schema_version
            or dataset.canonicalizer_version != contract.canonicalizer_version
            or dataset.canonical_observation_sha256
            != contract.canonical_observation_sha256
            or actual_measurement_hash != dataset.canonical_observation_sha256
        ):
            raise ShadowAnalysisError(
                "ANALYSIS_CONTRACT_DATA_MISMATCH",
                "影子分析契约未绑定当前 mapping、schema、raw 或 canonical hash。",
            )
        if (
            dataset.storage_partition != SHADOW_STORAGE_PARTITION
            or dataset.eligible_for_training
            or dataset.eligible_for_approved_case_library
            or dataset.automatic_retraining_allowed
            or dataset.fixed_demo_asset_mutation_allowed
        ):
            raise ShadowAnalysisError(
                "ANALYSIS_ISOLATION_VIOLATION",
                "影子数据隔离标志无效，拒绝进入分析链路。",
            )
        if (
            report.status
            not in {
                ShadowDataStatus.INSUFFICIENT_DATA,
                ShadowDataStatus.NOT_EVALUABLE,
                ShadowDataStatus.READY,
            }
            or not report.features_computable
            or not report.sample_indexes_contiguous
            or len(dataset.measurements) != len(dataset.observation_contexts)
        ):
            raise ShadowAnalysisError(
                "ANALYSIS_DATA_NOT_READY",
                "影子数据未通过特征、SPC、连续性或上下文完整性门禁。",
            )

    def _load_assets(self, contract: ShadowAnalysisContract):
        try:
            diagnostic_assets = DiagnosticAssetLoader(
                self._diagnostic_asset_root,
                contract.diagnostic_asset_manifest_sha256,
            ).load()
            planning_assets = ParameterPlanningAssetLoader(
                self._planning_asset_root,
                contract.planning_asset_manifest_sha256,
            ).load()
        except (DiagnosticAssetError, ParameterPlanningAssetError) as error:
            raise ShadowAnalysisError(
                "ANALYSIS_ASSET_VALIDATION_FAILED", str(error)
            ) from error
        diagnostic_manifest = diagnostic_assets.manifest
        planning_manifest = planning_assets.manifest
        try:
            expected_controls = ControlLimitRegistry.snapshot_for(
                contract.rule_set_version
            )
            expected_spc_rules = SpcRuleRegistry.snapshot_for(
                contract.rule_set_version
            )
        except KeyError as error:
            raise ShadowAnalysisError(
                "ANALYSIS_RULE_SET_UNSUPPORTED",
                "分析契约声明的规则版本不受当前运行时支持。",
            ) from error
        if (
            contract.control_limits != expected_controls
            or contract.spc_rules != expected_spc_rules
            or diagnostic_manifest.get("model_version") != contract.model_version
            or diagnostic_manifest.get("preprocessing_version")
            != contract.preprocessing_version
            or diagnostic_manifest.get("feature_definition_version")
            != contract.feature_definition_version
            or planning_manifest.get("feature_definition_version")
            != contract.feature_definition_version
            or planning_manifest.get("rule_set_version") != contract.rule_set_version
            or planning_manifest.get("safety_rule_version")
            != contract.safety_rule_version
            or planning_assets.expected_parameter_constraint_snapshot_hash
            != contract.parameter_constraint_snapshot_sha256
        ):
            raise ShadowAnalysisError(
                "ANALYSIS_ASSET_VERSION_MISMATCH",
                "分析契约与当前诊断模型、规划规则或参数约束资产不一致。",
            )
        return diagnostic_assets, planning_assets

    @staticmethod
    def _groups(
        dataset: ImportedShadowDataset,
    ) -> tuple[tuple[str | None, str | None, tuple[dict[str, str], ...]], ...]:
        by_index = {
            measurement["sample_index"]: dict(measurement)
            for measurement in dataset.measurements
        }
        grouped: dict[
            tuple[str | None, str | None], list[dict[str, str]]
        ] = {}
        seen_context_indexes: set[str] = set()
        for context in dataset.observation_contexts:
            if context.sample_index in seen_context_indexes:
                raise ShadowAnalysisError(
                    "ANALYSIS_CONTEXT_MISMATCH",
                    "观测上下文包含重复 sample_index。",
                )
            measurement = by_index.get(context.sample_index)
            if measurement is None:
                raise ShadowAnalysisError(
                    "ANALYSIS_CONTEXT_MISMATCH",
                    "观测上下文无法绑定 canonical measurement。",
                )
            seen_context_indexes.add(context.sample_index)
            grouped.setdefault((context.batch_id, context.lot_id), []).append(
                measurement
            )
        if seen_context_indexes != set(by_index):
            raise ShadowAnalysisError(
                "ANALYSIS_CONTEXT_MISMATCH",
                "观测上下文未完整覆盖 canonical measurements。",
            )
        return tuple(
            (
                key[0],
                key[1],
                tuple(sorted(values, key=lambda item: int(item["sample_index"]))),
            )
            for key, values in sorted(
                grouped.items(), key=lambda item: _group_sort_key(item[0])
            )
        )

    @staticmethod
    def _analyze_group(
        dataset: ImportedShadowDataset,
        contract: ShadowAnalysisContract,
        *,
        batch_id: str | None,
        lot_id: str | None,
        measurements: tuple[dict[str, str], ...],
        diagnostic_assets,
        planning_assets,
    ) -> ShadowGroupAnalysis:
        measurement_hash = canonical_measurement_hash(measurements)
        group_identity = _canonical_hash(
            {"batch_id": batch_id, "lot_id": lot_id, "measurement_hash": measurement_hash}
        )
        detection = AnomalyDetector().detect(
            DetectionInput(
                task_id=f"shadow-{dataset.canonical_observation_sha256[:16]}",
                batch_id=batch_id or lot_id or f"shadow-group-{group_identity[:12]}",
                measurements=measurements,
                control_limits=contract.control_limits,
                rule_snapshot=contract.spc_rules,
                input_data_version=contract.input_data_version,
                input_hash=measurement_hash,
            )
        )
        if detection.anomaly_result is AnomalyResult.INSUFFICIENT_DATA:
            return ShadowGroupAnalysis(
                batch_id=batch_id,
                lot_id=lot_id,
                sample_count=len(measurements),
                measurement_hash=measurement_hash,
                detection_status="INSUFFICIENT_DATA",
                predicted_anomaly=None,
                detection_result_hash=detection.result_hash,
                diagnostic_status="NOT_RUN",
                ranked_root_causes=(),
                diagnostic_feature_hash=None,
                safety_candidate_status="NOT_RUN",
                predicted_parameter_direction=None,
                safety_candidates=(),
                refusal_code="INSUFFICIENT_DATA",
            )
        if detection.anomaly_result is not AnomalyResult.TARGET_ANOMALY:
            return ShadowGroupAnalysis(
                batch_id=batch_id,
                lot_id=lot_id,
                sample_count=len(measurements),
                measurement_hash=measurement_hash,
                detection_status="EVALUATED",
                predicted_anomaly=detection.anomaly_result.value,
                detection_result_hash=detection.result_hash,
                diagnostic_status="NOT_RUN_ANOMALY_NOT_TARGET",
                ranked_root_causes=(),
                diagnostic_feature_hash=None,
                safety_candidate_status="NOT_RUN",
                predicted_parameter_direction=None,
                safety_candidates=(),
                refusal_code="ANOMALY_RESULT_NOT_TARGET",
            )
        try:
            features = FeatureEngineer().derive(measurements)
            diagnosis = RootCauseDiagnoser(diagnostic_assets).diagnose(
                features, contract.control_limits
            )
        except (FeatureEngineeringError, DiagnosticGuardError) as error:
            diagnostic_status = (
                "FEATURE_UNAVAILABLE"
                if isinstance(error, FeatureEngineeringError)
                else "REJECTED"
            )
            return ShadowGroupAnalysis(
                batch_id=batch_id,
                lot_id=lot_id,
                sample_count=len(measurements),
                measurement_hash=measurement_hash,
                detection_status="EVALUATED",
                predicted_anomaly=detection.anomaly_result.value,
                detection_result_hash=detection.result_hash,
                diagnostic_status=diagnostic_status,
                ranked_root_causes=(),
                diagnostic_feature_hash=None,
                safety_candidate_status="NOT_RUN",
                predicted_parameter_direction=None,
                safety_candidates=(),
                refusal_code=error.code,
            )
        ranked = tuple(item.root_cause for item in diagnosis.ordered_top3)
        if diagnosis.evidence_status != "SUFFICIENT_EVIDENCE" or len(ranked) != 3:
            return _diagnosed_refusal(
                batch_id,
                lot_id,
                measurements,
                measurement_hash,
                detection,
                features.input_feature_hash,
                ranked,
                "INSUFFICIENT_EVIDENCE",
            )
        current_values: dict[str, str] = {}
        for name in PARAMETER_FIELDS:
            values = {measurement[name] for measurement in measurements}
            if len(values) != 1:
                return _diagnosed_refusal(
                    batch_id,
                    lot_id,
                    measurements,
                    measurement_hash,
                    detection,
                    features.input_feature_hash,
                    ranked,
                    "CURRENT_PARAMETER_STATE_INCONSISTENT",
                )
            current_values[name] = next(iter(values))
        current_refusal = validate_current_parameter_values(
            current_values, contract.parameter_constraints
        )
        if current_refusal is not None:
            return _diagnosed_refusal(
                batch_id,
                lot_id,
                measurements,
                measurement_hash,
                detection,
                features.input_feature_hash,
                ranked,
                current_refusal,
            )
        top1 = ranked[0]
        parameter_family = planning_assets.safety_policy.family_for_root_cause(top1)
        if parameter_family is None:
            return _diagnosed_refusal(
                batch_id,
                lot_id,
                measurements,
                measurement_hash,
                detection,
                features.input_feature_hash,
                ranked,
                "TOP1_PARAMETER_FAMILY_NOT_ALLOWED",
            )
        feature_values = {
            name: f"{value:.12f}"
            for name, value in zip(
                features.feature_names, features.values, strict=True
            )
        }
        direction = DirectionEvidenceGenerator(
            planning_assets.direction_rules
        ).generate(
            root_cause=top1,
            current_values=current_values,
            features=feature_values,
            snapshot=contract.parameter_constraints,
            diagnostic_result_version=DIAGNOSTIC_RESULT_VERSION,
            feature_definition_version=contract.feature_definition_version,
            z_gate_passed=diagnosis.z_gate_result.passed,
        )
        if not direction.usable_evidence:
            return _diagnosed_refusal(
                batch_id,
                lot_id,
                measurements,
                measurement_hash,
                detection,
                features.input_feature_hash,
                ranked,
                direction.refusal_code or "NO_CLEAR_DIRECTION_EVIDENCE",
            )
        generated = ParameterPlanGenerator(
            validator=ParameterSafetyValidator(planning_assets.safety_policy),
            planning_policy=planning_assets.planning_policy,
        ).generate(
            root_cause=top1,
            parameter_family=parameter_family,
            current_values=current_values,
            direction_evidence=direction.usable_evidence,
            snapshot=contract.parameter_constraints,
            diagnostic_result_version=DIAGNOSTIC_RESULT_VERSION,
            case_retrieval_result_version=None,
            cases=(),
            feature_definition_version=contract.feature_definition_version,
            product_model=contract.product_model,
        )
        candidates = tuple(
            ShadowSafetyCandidate(
                candidate_id=candidate.candidate_id,
                generation_type=candidate.generation_type,
                root_cause=candidate.root_cause,
                parameter_family=candidate.parameter_family,
                changed_parameters=tuple(sorted(candidate.delta_ticks)),
                proposed_values=tuple(
                    (name, candidate.proposed_values[name])
                    for name in sorted(candidate.delta_ticks)
                ),
                delta_ticks=tuple(sorted(candidate.delta_ticks.items())),
                validation_status=candidate.validation_status,
                safety_rule_version=candidate.safety_rule_version,
                constraint_snapshot_version=candidate.constraint_snapshot_version,
                candidate_hash=candidate.candidate_hash,
            )
            for candidate in generated.ordered_candidates
            if candidate.validation_status == "PASSED"
        )
        if not candidates:
            return _diagnosed_refusal(
                batch_id,
                lot_id,
                measurements,
                measurement_hash,
                detection,
                features.input_feature_hash,
                ranked,
                "NO_SAFE_CANDIDATE",
            )
        directions = {
            item.recommended_direction for item in direction.usable_evidence
        }
        predicted_direction = next(iter(directions)) if len(directions) == 1 else None
        return ShadowGroupAnalysis(
            batch_id=batch_id,
            lot_id=lot_id,
            sample_count=len(measurements),
            measurement_hash=measurement_hash,
            detection_status="EVALUATED",
            predicted_anomaly=detection.anomaly_result.value,
            detection_result_hash=detection.result_hash,
            diagnostic_status="EVALUATED",
            ranked_root_causes=ranked,
            diagnostic_feature_hash=features.input_feature_hash,
            safety_candidate_status="PASSED",
            predicted_parameter_direction=predicted_direction,
            safety_candidates=candidates,
            refusal_code=None,
        )


def shadow_analysis_result_hash(result: ShadowAnalysisResult) -> str:
    payload = asdict(result)
    payload.pop("analysis_result_id", None)
    payload.pop("analysis_result_hash", None)
    envelope = {
        "canonicalizer_version": SHADOW_ANALYSIS_CANONICALIZER_VERSION,
        "business_content": payload,
    }
    return _canonical_hash(envelope)


def _diagnosed_refusal(
    batch_id: str | None,
    lot_id: str | None,
    measurements: tuple[dict[str, str], ...],
    measurement_hash: str,
    detection,
    feature_hash: str,
    ranked: tuple[str, ...],
    refusal_code: str,
) -> ShadowGroupAnalysis:
    return ShadowGroupAnalysis(
        batch_id=batch_id,
        lot_id=lot_id,
        sample_count=len(measurements),
        measurement_hash=measurement_hash,
        detection_status="EVALUATED",
        predicted_anomaly=detection.anomaly_result.value,
        detection_result_hash=detection.result_hash,
        diagnostic_status="EVALUATED",
        ranked_root_causes=ranked,
        diagnostic_feature_hash=feature_hash,
        safety_candidate_status="REJECTED",
        predicted_parameter_direction=None,
        safety_candidates=(),
        refusal_code=refusal_code,
    )


def _parameter_state_ready(
    measurements: tuple[dict[str, str], ...],
    snapshot: ParameterConstraintSnapshot,
) -> bool:
    current_values: dict[str, str] = {}
    for name in PARAMETER_FIELDS:
        try:
            values = {measurement[name] for measurement in measurements}
        except (KeyError, TypeError):
            return False
        if len(values) != 1:
            return False
        current_values[name] = next(iter(values))
    return validate_current_parameter_values(current_values, snapshot) is None


def _parse_control_limits(payload: Any) -> ControlLimitSnapshot:
    expected = {
        "snapshot_version",
        "rule_set_version",
        "center_lower_limit",
        "corner_lower_limit",
        "asymmetry_limit",
        "corner_std_limit",
    }
    _require_exact_mapping(payload, expected, "control_limits")
    values = {
        field: _required_decimal(payload[field], field)
        for field in expected - {"snapshot_version", "rule_set_version"}
    }
    if any(value < 0 or value > 1 for value in values.values()):
        raise ShadowAnalysisError(
            "ANALYSIS_CONTRACT_INVALID", "控制限必须位于 0 到 1。"
        )
    return ControlLimitSnapshot(
        snapshot_version=_required_text(payload["snapshot_version"], "snapshot_version"),
        rule_set_version=_required_text(payload["rule_set_version"], "rule_set_version"),
        center_lower_limit=values["center_lower_limit"],
        corner_lower_limit=values["corner_lower_limit"],
        asymmetry_limit=values["asymmetry_limit"],
        corner_std_limit=values["corner_std_limit"],
    )


def _parse_spc_rules(payload: Any) -> SpcRuleSnapshot:
    expected = {
        "snapshot_version",
        "rule_set_version",
        "minimum_sample_count",
        "minimum_consecutive_violations",
        "minimum_violation_ratio",
        "center_clear_degradation_margin",
        "global_corner_fraction",
    }
    _require_exact_mapping(payload, expected, "spc_rules")
    counts = (
        payload["minimum_sample_count"],
        payload["minimum_consecutive_violations"],
    )
    if any(not isinstance(value, int) or isinstance(value, bool) or value <= 0 for value in counts):
        raise ShadowAnalysisError(
            "ANALYSIS_CONTRACT_INVALID", "SPC 样本数和持续违例数必须为正整数。"
        )
    ratio = _required_decimal(
        payload["minimum_violation_ratio"], "minimum_violation_ratio"
    )
    margin = _required_decimal(
        payload["center_clear_degradation_margin"],
        "center_clear_degradation_margin",
    )
    fraction = _required_decimal(
        payload["global_corner_fraction"], "global_corner_fraction"
    )
    if not (0 <= ratio <= 1 and 0 <= margin <= 1 and 0 < fraction <= 1):
        raise ShadowAnalysisError(
            "ANALYSIS_CONTRACT_INVALID", "SPC 比例或 margin 超出允许范围。"
        )
    return SpcRuleSnapshot(
        snapshot_version=_required_text(payload["snapshot_version"], "snapshot_version"),
        rule_set_version=_required_text(payload["rule_set_version"], "rule_set_version"),
        minimum_sample_count=counts[0],
        minimum_consecutive_violations=counts[1],
        minimum_violation_ratio=ratio,
        center_clear_degradation_margin=margin,
        global_corner_fraction=fraction,
    )


def _parse_parameter_constraints(payload: Any) -> ParameterConstraintSnapshot:
    _require_exact_mapping(
        payload,
        {"snapshot_version", "product_model", "rule_set_version", "constraints"},
        "parameter_constraints",
    )
    constraints_payload = payload["constraints"]
    if not isinstance(constraints_payload, Mapping) or set(constraints_payload) != set(
        PARAMETER_FIELDS
    ):
        raise ShadowAnalysisError(
            "ANALYSIS_CONTRACT_INVALID",
            "参数约束必须完整覆盖冻结参数白名单。",
        )
    constraints: list[ParameterConstraint] = []
    expected_fields = {
        "nominal_value",
        "minimum",
        "maximum",
        "step",
        "maximum_single_plan_delta",
    }
    for name in sorted(PARAMETER_FIELDS):
        item = constraints_payload[name]
        _require_exact_mapping(item, expected_fields, f"constraints.{name}")
        decimals = {field: _required_decimal(item[field], field) for field in expected_fields}
        if (
            decimals["step"] <= 0
            or decimals["maximum_single_plan_delta"] < 0
            or not (
                decimals["minimum"]
                <= decimals["nominal_value"]
                <= decimals["maximum"]
            )
        ):
            raise ShadowAnalysisError(
                "ANALYSIS_CONTRACT_INVALID", f"{name} 参数约束边界无效。"
            )
        constraints.append(
            ParameterConstraint(
                parameter_name=name,
                nominal_value=item["nominal_value"],
                minimum=item["minimum"],
                maximum=item["maximum"],
                step=item["step"],
                maximum_single_plan_delta=item["maximum_single_plan_delta"],
            )
        )
    return ParameterConstraintSnapshot(
        snapshot_version=_required_text(payload["snapshot_version"], "snapshot_version"),
        product_model=_required_text(payload["product_model"], "product_model"),
        rule_set_version=_required_text(payload["rule_set_version"], "rule_set_version"),
        constraints=tuple(constraints),
    )


def _control_limit_payload(snapshot: ControlLimitSnapshot) -> dict[str, Any]:
    return {
        "snapshot_version": snapshot.snapshot_version,
        "rule_set_version": snapshot.rule_set_version,
        "center_lower_limit": _decimal_text(snapshot.center_lower_limit),
        "corner_lower_limit": _decimal_text(snapshot.corner_lower_limit),
        "asymmetry_limit": _decimal_text(snapshot.asymmetry_limit),
        "corner_std_limit": _decimal_text(snapshot.corner_std_limit),
    }


def _spc_rule_payload(snapshot: SpcRuleSnapshot) -> dict[str, Any]:
    return {
        "snapshot_version": snapshot.snapshot_version,
        "rule_set_version": snapshot.rule_set_version,
        "minimum_sample_count": snapshot.minimum_sample_count,
        "minimum_consecutive_violations": snapshot.minimum_consecutive_violations,
        "minimum_violation_ratio": _decimal_text(snapshot.minimum_violation_ratio),
        "center_clear_degradation_margin": _decimal_text(
            snapshot.center_clear_degradation_margin
        ),
        "global_corner_fraction": _decimal_text(snapshot.global_corner_fraction),
    }


def _parameter_snapshot_payload(snapshot: ParameterConstraintSnapshot) -> dict[str, Any]:
    return {
        "snapshot_version": snapshot.snapshot_version,
        "product_model": snapshot.product_model,
        "rule_set_version": snapshot.rule_set_version,
        "constraints": {
            item.parameter_name: {
                "nominal_value": item.nominal_value,
                "minimum": item.minimum,
                "maximum": item.maximum,
                "step": item.step,
                "maximum_single_plan_delta": item.maximum_single_plan_delta,
            }
            for item in snapshot.constraints
        },
    }


def _parameter_snapshot_hash(snapshot: ParameterConstraintSnapshot) -> str:
    content = (
        json.dumps(
            _parameter_snapshot_payload(snapshot),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ShadowAnalysisError(
            "ANALYSIS_CONTRACT_INVALID", f"{field} 必须是非空字符串。"
        )
    return value


def _required_sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None:
        raise ShadowAnalysisError(
            "ANALYSIS_CONTRACT_INVALID", f"{field} 必须是小写 SHA-256。"
        )
    return value


def _required_decimal(value: Any, field: str) -> Decimal:
    if not isinstance(value, str):
        raise ShadowAnalysisError(
            "ANALYSIS_CONTRACT_INVALID", f"{field} 必须是 Decimal 字符串。"
        )
    try:
        parsed = Decimal(value)
        quantized = parsed.quantize(CANONICAL_PRECISION)
    except InvalidOperation as error:
        raise ShadowAnalysisError(
            "ANALYSIS_CONTRACT_INVALID", f"{field} 不是合法 Decimal。"
        ) from error
    if not parsed.is_finite() or parsed != quantized:
        raise ShadowAnalysisError(
            "ANALYSIS_CONTRACT_INVALID", f"{field} 必须是最多六位小数的有限值。"
        )
    return parsed


def _require_exact_mapping(payload: Any, fields: set[str], name: str) -> None:
    if not isinstance(payload, Mapping) or set(payload) != fields:
        raise ShadowAnalysisError(
            "ANALYSIS_CONTRACT_INVALID", f"{name} 字段不完整或包含未定义字段。"
        )


def _decimal_text(value: Decimal) -> str:
    return format(value.quantize(CANONICAL_PRECISION), "f")


def _canonical_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            _plain(payload),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _plain(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Decimal):
        return _decimal_text(value)
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _group_sort_key(key: tuple[str | None, str | None]) -> tuple[str, str]:
    return key[0] or "", key[1] or ""
