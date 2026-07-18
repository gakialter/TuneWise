from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, replace
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Never

from .assets import AssetIntegrityError, PublicAssetLoader
from .case_retrieval import (
    CASE_RETRIEVAL_RESULT_VERSION,
    ApprovedCaseAssetLoader,
    CaseRetrievalAssetError,
    CaseRetrievalGuardError,
    CaseRetrievalResultRecord,
    StructuredCaseRetriever,
    record_case_retrieval,
)
from .domain import Task, TaskStatus, workflow_for
from .detection import (
    AnomalyDetectionRecord,
    AnomalyDetector,
    AnomalyResult,
    ControlLimitRegistry,
    ControlLimitSnapshot,
    DetectionGuardError,
    DetectionInput,
    SpcRuleRegistry,
    SystemClock,
    canonical_measurement_hash,
    deserialize_spc_rule_snapshot,
    record_detection,
    serialize_spc_rule_snapshot,
)
from .importing import DemoDatasetImporter, ImportValidationError
from .diagnosis import (
    DiagnosticAssetLoader,
    DiagnosticGuardError,
    DiagnosticResultRecord,
    FeatureEngineeringError,
    FeatureEngineer,
    RootCauseDiagnoser,
    record_diagnosis,
)
from .diagnostic_contract import (
    DIAGNOSTIC_RESULT_VERSION,
    EVIDENCE_RULE_VERSION,
    FEATURE_DEFINITION_VERSION,
    PARAMETER_FIELDS,
)
from .parameter_planning import (
    PLANNING_RESULT_VERSION,
    DirectionEvidenceGenerator,
    HistoricalCaseAction,
    ParameterConstraintSnapshot,
    ParameterPlanGenerator,
    ParameterSafetyValidator,
    SafetyVersionContext,
    ParameterPlanningAssetError,
    ParameterPlanningAssetLoader,
    ParameterPlanningGuardError,
    ParameterPlanningResultRecord,
    parameter_planning_input_hash,
    record_parameter_planning_refusal,
    record_parameter_planning,
    validate_current_parameter_values,
)
from .store import (
    CaseRetrievalResultConflictError,
    DiagnosticResultConflictError,
    DetectionResultConflictError,
    ImportSnapshotConflictError,
    StoredDetectionInput,
    TaskStore,
    ParameterPlanningResultConflictError,
)


@dataclass(frozen=True, slots=True)
class DemoTaskIdGenerator:
    def new_id(self) -> str:
        return "tw-demo-task-001"


@dataclass(slots=True)
class PlanningBoundaryAudit:
    counters: dict[str, int] = field(
        default_factory=lambda: {
            "simulator_gateway_assemblies": 0,
            "simulator_gateway_calls": 0,
            "llm_calls": 0,
            "external_network_requests": 0,
        }
    )

    def record(self, boundary: str) -> None:
        self.counters[boundary] += 1

    def assert_pristine(self) -> None:
        attempted = {
            name: count for name, count in self.counters.items() if count != 0
        }
        if attempted:
            raise RuntimeError(f"参数规划隔离边界发生未授权调用：{attempted}")


class TaskService:
    def __init__(
        self,
        asset_loader: PublicAssetLoader,
        store: TaskStore,
        id_generator: DemoTaskIdGenerator | None = None,
        demo_asset_root: Path | None = None,
        expected_dataset_manifest_hash: str | None = None,
        clock: SystemClock | None = None,
        diagnostic_asset_root: Path | None = None,
        expected_diagnostic_manifest_hash: str | None = None,
        case_asset_root: Path | None = None,
        expected_case_manifest_hash: str | None = None,
        planning_asset_root: Path | None = None,
        expected_planning_manifest_hash: str | None = None,
        planning_boundary_audit: PlanningBoundaryAudit | None = None,
    ) -> None:
        self._asset_loader = asset_loader
        self._store = store
        self._id_generator = id_generator or DemoTaskIdGenerator()
        self._demo_asset_root = demo_asset_root
        self._expected_dataset_manifest_hash = expected_dataset_manifest_hash
        self._clock = clock or SystemClock()
        self._diagnostic_asset_root = diagnostic_asset_root
        self._expected_diagnostic_manifest_hash = expected_diagnostic_manifest_hash
        self._case_asset_root = case_asset_root
        self._expected_case_manifest_hash = expected_case_manifest_hash
        self._planning_asset_root = planning_asset_root
        self._expected_planning_manifest_hash = expected_planning_manifest_hash
        self._planning_boundary_audit = (
            planning_boundary_audit or PlanningBoundaryAudit()
        )

    def create_initial_task(self) -> Task:
        assets = self._asset_loader.load()
        task = Task(
            task_id=self._id_generator.new_id(),
            status=TaskStatus.CREATED,
            actor=assets.actor,
            versions=assets.versions,
            stages=workflow_for(TaskStatus.CREATED),
        )
        return self._store.get_or_create(task)

    def get_task(self, task_id: str) -> Task | None:
        assets = self._asset_loader.load()
        task = self._store.get(task_id)
        if task is not None and (
            task.actor != assets.actor or task.versions != assets.versions
        ):
            raise AssetIntegrityError(
                "TASK_ASSET_SNAPSHOT_MISMATCH",
                "任务绑定的公共版本快照与当前资产不一致。",
            )
        return task

    def record_parameter_planning_request_refusal(
        self,
        task_id: str,
        requested_diagnostic_result_id: str,
        requested_case_retrieval_result_id: str | None,
        forbidden_fields: tuple[str, ...],
    ) -> ParameterPlanningGuardError:
        task = self._store.get(task_id)
        if task is None:
            return ParameterPlanningGuardError(
                "TASK_NOT_FOUND", "调机任务不存在。", 404
            )
        code = "PARAMETER_PLANNING_REQUEST_FORBIDDEN_FIELDS"
        message = "参数规划请求只能引用最新诊断与可选的最新案例检索结果。"
        supporting_evidence = (
            f"forbidden_fields={','.join(forbidden_fields)}",
        )
        record = record_parameter_planning_refusal(
            task_id=task.task_id,
            requested_diagnostic_result_id=requested_diagnostic_result_id,
            requested_case_retrieval_result_id=requested_case_retrieval_result_id,
            refusal_code=code,
            refusal_message=message,
            supporting_evidence=supporting_evidence,
            recommended_inspection_actions=(),
            rule_set_version=task.versions.rule_set_version,
            created_at=self._clock.now(),
        )
        self._store.save_parameter_planning_refusal(record)
        return ParameterPlanningGuardError(
            code,
            message,
            422,
            supporting_evidence=supporting_evidence,
            rule_set_version=task.versions.rule_set_version,
        )

    def import_preset(self, task_id: str, preset_asset_id: str) -> Task:
        assets = self._asset_loader.load()
        task = self._store.get(task_id)
        if task is None:
            raise ImportValidationError("TASK_NOT_FOUND", "调机任务不存在。", 404)
        if task.actor != assets.actor or task.versions != assets.versions:
            raise AssetIntegrityError(
                "TASK_ASSET_SNAPSHOT_MISMATCH",
                "任务绑定的公共版本快照与当前资产不一致。",
            )
        if task.status not in (TaskStatus.CREATED, TaskStatus.DATA_IMPORTED):
            raise ImportValidationError("TASK_STATE_INVALID", "当前任务状态不允许导入数据。", 409)
        if self._demo_asset_root is None or self._expected_dataset_manifest_hash is None:
            raise ImportValidationError("DATASET_ASSET_MISSING", "预置演示资产不可用。", 409)
        imported = DemoDatasetImporter(
            self._demo_asset_root,
            self._expected_dataset_manifest_hash,
            task.versions,
        ).load(preset_asset_id)
        if task.status == TaskStatus.DATA_IMPORTED and task.data_import is not None:
            if task.data_import != imported.summary:
                raise ImportValidationError(
                    "IMPORTED_DATA_SNAPSHOT_MISMATCH",
                    "当前演示资产与任务已保存的数据快照不匹配。",
                    409,
                )
            return task
        imported_task = replace(
            task,
            status=TaskStatus.DATA_IMPORTED,
            stages=workflow_for(TaskStatus.DATA_IMPORTED),
            data_import=imported.summary,
        )
        try:
            return self._store.save_import(
                imported_task,
                manifest=imported.manifest,
                batch=imported.batch,
                measurements=imported.measurements,
                control_limits=imported.control_limits,
                parameter_constraints=imported.parameter_constraints,
                replay_evaluation_rules=imported.replay_evaluation_rules,
                spc_rules=serialize_spc_rule_snapshot(
                    SpcRuleRegistry.snapshot_for(task.versions.rule_set_version)
                ),
            )
        except ImportSnapshotConflictError as error:
            stored = self._store.get(task_id)
            if (
                stored is not None
                and stored.status == TaskStatus.DATA_IMPORTED
                and stored.data_import == imported.summary
            ):
                return stored
            raise ImportValidationError(
                "IMPORT_SNAPSHOT_CONFLICT",
                "当前任务的数据导入快照已发生变化。",
                409,
            )

    def detect_anomaly(
        self,
        task_id: str,
        input_data_version: str,
    ) -> tuple[Task, AnomalyDetectionRecord]:
        assets = self._asset_loader.load()
        task = self._store.get(task_id)
        if task is None:
            raise DetectionGuardError(
                "TASK_NOT_FOUND", "调机任务不存在。", 404
            )
        if task.actor != assets.actor or task.versions != assets.versions:
            raise AssetIntegrityError(
                "TASK_ASSET_SNAPSHOT_MISMATCH",
                "任务绑定的公共版本快照与当前资产不一致。",
            )
        if input_data_version != task.versions.dataset_version:
            raise DetectionGuardError(
                "DETECTION_INPUT_VERSION_STALE",
                "请求的数据版本不是当前任务最新导入版本。",
            )
        has_current_result = task.anomaly_detection is not None
        if task.status is not TaskStatus.DATA_IMPORTED and not (
            task.status is TaskStatus.ANOMALY_DETECTED and has_current_result
        ):
            raise DetectionGuardError(
                "DETECTION_TASK_STATE_INVALID",
                "只有 DATA_IMPORTED 任务可以运行异常检测。",
            )
        if task.data_import is None:
            raise DetectionGuardError(
                "DETECTION_INPUT_MISSING",
                "当前任务缺少已导入 Batch 数据。",
            )
        source = self._store.get_detection_input(task_id)
        detection_input = self._validated_detection_input(task, source)
        if has_current_result:
            current = task.anomaly_detection
            if (
                current.input_data_version != detection_input.input_data_version
                or current.input_hash != detection_input.input_hash
                or current.rule_set_version != detection_input.rule_snapshot.rule_set_version
            ):
                raise DetectionGuardError(
                    "DETECTION_CURRENT_RESULT_STALE",
                    "当前检测结果与最新输入或规则版本不一致。",
                )
            return task, current

        decision = AnomalyDetector().detect(detection_input)
        record = record_detection(decision, created_at=self._clock.now())
        next_status = (
            TaskStatus.ANOMALY_DETECTED
            if record.anomaly_result is AnomalyResult.TARGET_ANOMALY
            else TaskStatus.DATA_IMPORTED
        )
        updated_task = replace(
            task,
            status=next_status,
            stages=workflow_for(next_status),
            anomaly_detection=record,
        )
        try:
            return self._store.save_detection(updated_task, record)
        except DetectionResultConflictError as error:
            stored = self._store.get(task_id)
            if (
                stored is not None
                and stored.anomaly_detection is not None
                and stored.anomaly_detection.detection_result_id
                == record.detection_result_id
            ):
                return stored, stored.anomaly_detection
            raise DetectionGuardError(
                "DETECTION_RESULT_CONFLICT",
                "当前任务的检测结果已发生冲突。",
            )

    def diagnose_root_cause(
        self,
        task_id: str,
        detection_result_id: str,
    ) -> tuple[Task, DiagnosticResultRecord]:
        assets = self._asset_loader.load()
        task = self._store.get(task_id)
        if task is None:
            raise DiagnosticGuardError("TASK_NOT_FOUND", "调机任务不存在。", 404)
        if task.actor != assets.actor or task.versions != assets.versions:
            raise AssetIntegrityError(
                "TASK_ASSET_SNAPSHOT_MISMATCH",
                "任务绑定的公共版本快照与当前资产不一致。",
            )
        current = task.diagnostic_result
        if task.status is TaskStatus.DIAGNOSED and current is not None:
            if current.detection_result_id != detection_result_id:
                raise DiagnosticGuardError(
                    "DIAGNOSTIC_CURRENT_RESULT_CONFLICT",
                    "当前任务已有不同检测引用的诊断结果。",
                )
            return task, current
        if task.status is not TaskStatus.ANOMALY_DETECTED:
            raise DiagnosticGuardError(
                "DIAGNOSTIC_TASK_STATE_INVALID",
                "只有 ANOMALY_DETECTED 任务可以运行根因诊断。",
            )
        detection = task.anomaly_detection
        if detection is None:
            raise DiagnosticGuardError(
                "DIAGNOSTIC_DETECTION_MISSING", "当前任务缺少最新异常检测结果。"
            )
        if detection.detection_result_id != detection_result_id:
            raise DiagnosticGuardError(
                "DIAGNOSTIC_DETECTION_STALE", "请求的检测结果不是当前任务最新版本。"
            )
        if detection.anomaly_result is not AnomalyResult.TARGET_ANOMALY:
            raise DiagnosticGuardError(
                "DIAGNOSTIC_ANOMALY_NOT_TARGET",
                "只有 TARGET_ANOMALY 检测结果可以运行根因诊断。",
            )
        source = self._store.get_detection_input(task_id)
        detection_input = self._validated_detection_input(task, source)
        if (
            detection.input_data_version != detection_input.input_data_version
            or detection.input_hash != detection_input.input_hash
            or detection.rule_set_version != detection_input.rule_snapshot.rule_set_version
            or detection.control_limit_snapshot_version
            != detection_input.control_limits.snapshot_version
        ):
            raise DiagnosticGuardError(
                "DIAGNOSTIC_DETECTION_STALE",
                "检测结果与当前输入、控制限或规则版本不一致。",
            )
        if self._diagnostic_asset_root is None or self._expected_diagnostic_manifest_hash is None:
            raise DiagnosticGuardError(
                "DIAGNOSTIC_ASSETS_MISSING", "固定诊断资产未装配。"
            )
        diagnostic_assets = DiagnosticAssetLoader(
            self._diagnostic_asset_root,
            self._expected_diagnostic_manifest_hash,
        ).load()
        if (
            diagnostic_assets.model.get("model_version") != task.versions.model_version
            or diagnostic_assets.preprocessing.get("preprocessing_version")
            != task.versions.preprocessing_version
        ):
            raise DiagnosticGuardError(
                "DIAGNOSTIC_ASSET_VERSION_STALE",
                "诊断模型或预处理器版本不是任务当前版本。",
            )
        features = FeatureEngineer().derive(detection_input.measurements)
        decision = RootCauseDiagnoser(diagnostic_assets).diagnose(
            features, detection_input.control_limits
        )
        record = record_diagnosis(
            decision,
            task_id=task.task_id,
            detection_result_id=detection.detection_result_id,
            input_data_version=detection_input.input_data_version,
            input_feature_hash=features.input_feature_hash,
            anomaly_result=detection.anomaly_result.value,
            created_at=self._clock.now(),
        )
        diagnosed_task = replace(
            task,
            status=TaskStatus.DIAGNOSED,
            stages=workflow_for(TaskStatus.DIAGNOSED),
            diagnostic_result=record,
        )
        try:
            return self._store.save_diagnosis(diagnosed_task, record)
        except DiagnosticResultConflictError as error:
            stored = self._store.get(task_id)
            if (
                stored is not None
                and stored.diagnostic_result is not None
                and stored.diagnostic_result.diagnostic_result_id
                == record.diagnostic_result_id
            ):
                return stored, stored.diagnostic_result
            raise DiagnosticGuardError(
                "DIAGNOSTIC_RESULT_CONFLICT",
                "当前任务的诊断结果已发生冲突。",
            ) from error

    def retrieve_approved_cases(
        self,
        task_id: str,
        diagnostic_result_id: str,
        top_k: int,
    ) -> tuple[Task, CaseRetrievalResultRecord]:
        public_assets = self._asset_loader.load()
        task = self._store.get(task_id)
        if task is None:
            raise CaseRetrievalGuardError("TASK_NOT_FOUND", "调机任务不存在。", 404)
        if task.actor != public_assets.actor or task.versions != public_assets.versions:
            raise AssetIntegrityError(
                "TASK_ASSET_SNAPSHOT_MISMATCH",
                "任务绑定的公共版本快照与当前资产不一致。",
            )
        if task.status is not TaskStatus.DIAGNOSED:
            raise CaseRetrievalGuardError(
                "CASE_RETRIEVAL_TASK_STATE_INVALID",
                "只有 DIAGNOSED 任务可以检索已审核案例。",
            )
        diagnostic = task.diagnostic_result
        if diagnostic is None:
            raise CaseRetrievalGuardError(
                "CASE_RETRIEVAL_DIAGNOSTIC_MISSING",
                "当前任务缺少最新诊断结果。",
            )
        if diagnostic.diagnostic_result_id != diagnostic_result_id:
            raise CaseRetrievalGuardError(
                "CASE_RETRIEVAL_DIAGNOSTIC_STALE",
                "请求的诊断结果不是当前任务最新版本。",
            )
        self._validate_diagnostic_for_retrieval(task, diagnostic)
        data_import = task.data_import
        if data_import is None:
            raise CaseRetrievalGuardError(
                "CASE_RETRIEVAL_BATCH_MISSING", "当前任务缺少已导入 Batch。"
            )
        measurements = self._store.get_observable_measurements(task_id)
        try:
            current_observation_hash = canonical_measurement_hash(measurements)
        except DetectionGuardError as error:
            raise CaseRetrievalGuardError(
                "CASE_RETRIEVAL_QUERY_INPUT_INVALID",
                "当前可观测 Measurement 无法按冻结契约规范化。",
                error.status_code,
            ) from error
        if current_observation_hash != data_import.hashes.canonical_observation_hash:
            raise CaseRetrievalGuardError(
                "CASE_RETRIEVAL_QUERY_INPUT_HASH_MISMATCH",
                "当前可观测 Measurement 与诊断输入数据版本不一致。",
            )
        try:
            query_features = FeatureEngineer().derive(measurements)
        except FeatureEngineeringError as error:
            code = (
                "CASE_QUERY_FEATURE_MISSING"
                if error.code == "DIAGNOSTIC_FEATURE_MISSING"
                else "CASE_QUERY_FEATURE_NON_FINITE"
                if error.code == "DIAGNOSTIC_FEATURE_NON_FINITE"
                else "CASE_QUERY_FEATURE_INVALID"
            )
            raise CaseRetrievalGuardError(code, error.message) from error
        if query_features.input_feature_hash != diagnostic.input_feature_hash:
            raise CaseRetrievalGuardError(
                "CASE_RETRIEVAL_QUERY_FEATURE_STALE",
                "当前 DerivedFeatureSet 与诊断输入版本不一致。",
            )
        if (
            self._case_asset_root is None
            or self._expected_case_manifest_hash is None
        ):
            raise CaseRetrievalAssetError(
                "CASE_ASSETS_MISSING", "固定 APPROVED 案例检索资产未装配。"
            )
        case_assets = ApprovedCaseAssetLoader(
            self._case_asset_root,
            self._expected_case_manifest_hash,
        ).load()
        if case_assets.manifest.get("rule_set_version") != task.versions.rule_set_version:
            raise CaseRetrievalAssetError(
                "CASE_ASSET_RULE_VERSION_STALE",
                "案例索引绑定的规则版本不是任务当前版本。",
            )
        top3_root_causes = tuple(
            candidate.root_cause for candidate in diagnostic.ordered_top3
        )
        decision = StructuredCaseRetriever(case_assets).retrieve(
            query_features=query_features,
            product_model=data_import.product_model,
            top3_root_causes=top3_root_causes,
            top_k=top_k,
        )
        record = record_case_retrieval(
            decision,
            task_id=task.task_id,
            diagnostic_result_id=diagnostic.diagnostic_result_id,
            ordered_top3_root_causes=top3_root_causes,
            created_at=self._clock.now(),
        )
        try:
            return self._store.save_case_retrieval(task, record)
        except CaseRetrievalResultConflictError as error:
            current = self._store.get_current_case_retrieval(task_id)
            if (
                current is not None
                and current.retrieval_result_id == record.retrieval_result_id
                and current.result_hash == record.result_hash
            ):
                stored_task = self._store.get(task_id)
                if stored_task is not None:
                    return stored_task, current
            raise CaseRetrievalGuardError(
                "CASE_RETRIEVAL_RESULT_CONFLICT",
                "当前任务的案例检索结果已发生冲突。",
            ) from error

    def generate_parameter_plans(
        self,
        task_id: str,
        diagnostic_result_id: str,
        case_retrieval_result_id: str | None,
    ) -> tuple[Task, ParameterPlanningResultRecord]:
        self._planning_boundary_audit.assert_pristine()
        public_assets = self._asset_loader.load()
        task = self._store.get(task_id)
        if task is None:
            raise ParameterPlanningGuardError("TASK_NOT_FOUND", "调机任务不存在。", 404)
        if task.actor != public_assets.actor or task.versions != public_assets.versions:
            raise AssetIntegrityError(
                "TASK_ASSET_SNAPSHOT_MISMATCH",
                "任务绑定的公共版本快照与当前资产不一致。",
            )
        current_planning = self._store.get_current_parameter_planning(task_id)
        if current_planning is not None:
            if (
                current_planning.diagnostic_result_id != diagnostic_result_id
                or current_planning.case_retrieval_result_id
                != case_retrieval_result_id
            ):
                self._raise_planning_guard(
                    task,
                    diagnostic_result_id,
                    case_retrieval_result_id,
                    "PARAMETER_PLANNING_CURRENT_RESULT_CONFLICT",
                    "当前任务已有不同输入绑定的参数规划结果。",
                )
            if task.status not in (TaskStatus.DIAGNOSED, TaskStatus.PLAN_READY):
                self._raise_planning_guard(
                    task,
                    diagnostic_result_id,
                    case_retrieval_result_id,
                    "PARAMETER_PLANNING_TASK_STATE_INVALID",
                    "当前任务状态不允许返回参数规划结果。",
                )
            return self._validated_current_planning(task, current_planning)
        if task.status is not TaskStatus.DIAGNOSED:
            self._raise_planning_guard(
                task,
                diagnostic_result_id,
                case_retrieval_result_id,
                "PARAMETER_PLANNING_TASK_STATE_INVALID",
                "只有 DIAGNOSED 任务可以生成安全参数候选。",
                supporting_evidence=(f"task_status={task.status.value}",),
            )
        diagnostic = task.diagnostic_result
        if diagnostic is None:
            self._raise_planning_guard(
                task,
                diagnostic_result_id,
                case_retrieval_result_id,
                "PARAMETER_PLANNING_DIAGNOSTIC_MISSING",
                "当前任务缺少最新诊断结果。",
            )
        if diagnostic.diagnostic_result_id != diagnostic_result_id:
            self._raise_planning_guard(
                task,
                diagnostic_result_id,
                case_retrieval_result_id,
                "PARAMETER_PLANNING_DIAGNOSTIC_STALE",
                "请求的诊断结果不是当前任务最新版本。",
                supporting_evidence=(
                    f"current_diagnostic_result_id={diagnostic.diagnostic_result_id}",
                ),
            )
        try:
            self._validate_diagnostic_for_retrieval(task, diagnostic)
        except CaseRetrievalGuardError as error:
            self._raise_planning_guard(
                task,
                diagnostic_result_id,
                case_retrieval_result_id,
                "PARAMETER_PLANNING_DIAGNOSTIC_STALE",
                "当前诊断结果与任务可观测输入或版本不一致。",
                status_code=error.status_code,
                supporting_evidence=(f"diagnostic_guard={error.code}",),
            )
        retrieval = self._store.get_current_case_retrieval(task_id)
        if (retrieval is None) != (case_retrieval_result_id is None) or (
            retrieval is not None
            and retrieval.retrieval_result_id != case_retrieval_result_id
        ):
            self._raise_planning_guard(
                task,
                diagnostic_result_id,
                case_retrieval_result_id,
                "PARAMETER_PLANNING_RETRIEVAL_STALE",
                "案例检索引用缺失、过期或不是当前版本。",
                supporting_evidence=(
                    f"current_case_retrieval_result_id={None if retrieval is None else retrieval.retrieval_result_id}",
                ),
            )
        if retrieval is not None and (
            retrieval.diagnostic_result_id != diagnostic.diagnostic_result_id
            or retrieval.query_feature_hash != diagnostic.input_feature_hash
            or retrieval.feature_definition_version != diagnostic.feature_definition_version
            or retrieval.retrieval_result_version != CASE_RETRIEVAL_RESULT_VERSION
        ):
            self._raise_planning_guard(
                task,
                diagnostic_result_id,
                case_retrieval_result_id,
                "PARAMETER_PLANNING_RETRIEVAL_STALE",
                "案例检索结果与当前诊断或特征版本不一致。",
            )
        if self._planning_asset_root is None or self._expected_planning_manifest_hash is None:
            self._raise_planning_guard(
                task,
                diagnostic_result_id,
                case_retrieval_result_id,
                "PLANNING_ASSETS_MISSING", "固定参数规划规则资产未装配。"
            )
        try:
            planning_assets = ParameterPlanningAssetLoader(
                self._planning_asset_root,
                self._expected_planning_manifest_hash,
            ).load()
        except ParameterPlanningAssetError as error:
            self._raise_planning_guard(
                task,
                diagnostic_result_id,
                case_retrieval_result_id,
                error.code,
                error.message,
                status_code=error.status_code,
            )
        if planning_assets.manifest.get("rule_set_version") != task.versions.rule_set_version:
            self._raise_planning_guard(
                task,
                diagnostic_result_id,
                case_retrieval_result_id,
                "PLANNING_ASSET_VERSION_STALE",
                "参数规划规则资产不是任务当前规则版本。",
            )
        source = self._store.get_planning_input(task_id)
        if (
            source.manifest is None
            or source.batch is None
            or source.control_limits is None
            or source.parameter_constraints is None
            or not source.measurements
            or task.data_import is None
        ):
            return self._save_planning_refusal(
                task,
                diagnostic,
                retrieval,
                planning_assets.manifest_hash,
                refusal_code="PLANNING_INPUT_OR_SNAPSHOT_MISSING",
                refusal_message="当前 Batch、控制限、参数快照或可观测输入不完整。",
                supporting_evidence=("任务持久化规划输入缺失。",),
            )
        try:
            snapshot = ParameterConstraintSnapshot.from_payload(
                source.parameter_constraints
            )
        except (KeyError, TypeError, ValueError) as error:
            return self._save_planning_refusal(
                task,
                diagnostic,
                retrieval,
                planning_assets.manifest_hash,
                refusal_code="PARAMETER_CONSTRAINT_SNAPSHOT_INVALID",
                refusal_message="参数约束快照格式无效。",
                supporting_evidence=(str(error),),
            )
        snapshot_hash = hashlib.sha256(
            (
                json.dumps(
                    source.parameter_constraints,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            ).encode("utf-8")
        ).hexdigest()
        if (
            snapshot_hash
            != planning_assets.expected_parameter_constraint_snapshot_hash
            or snapshot.snapshot_version
            != task.data_import.snapshot_versions.parameter_constraint_snapshot
            or snapshot.product_model != task.data_import.product_model
            or snapshot.rule_set_version != task.versions.rule_set_version
            or source.control_limits.get("snapshot_version")
            != task.data_import.snapshot_versions.control_limit_snapshot
            or source.control_limits.get("rule_set_version")
            != task.versions.rule_set_version
        ):
            return self._save_planning_refusal(
                task,
                diagnostic,
                retrieval,
                planning_assets.manifest_hash,
                refusal_code="PLANNING_SNAPSHOT_OR_RULE_TAMPERED",
                refusal_message="控制限、参数快照或规则版本缺失、过期或内容被修改。",
                supporting_evidence=(f"parameter_constraint_snapshot_hash={snapshot_hash}",),
                constraint_snapshot_version=snapshot.snapshot_version,
            )
        current_observation_hash = canonical_measurement_hash(source.measurements)
        if current_observation_hash != task.data_import.hashes.canonical_observation_hash:
            self._raise_planning_guard(
                task,
                diagnostic_result_id,
                case_retrieval_result_id,
                "PARAMETER_PLANNING_DIAGNOSTIC_STALE",
                "当前 Measurement 与诊断输入版本不一致。",
            )
        features = FeatureEngineer().derive(source.measurements)
        if features.input_feature_hash != diagnostic.input_feature_hash:
            self._raise_planning_guard(
                task,
                diagnostic_result_id,
                case_retrieval_result_id,
                "PARAMETER_PLANNING_DIAGNOSTIC_STALE",
                "当前 DerivedFeatureSet 与诊断输入版本不一致。",
            )
        current_values: dict[str, str] = {}
        for name in PARAMETER_FIELDS:
            try:
                values = {Decimal(row[name]) for row in source.measurements}
            except (KeyError, InvalidOperation, TypeError) as error:
                return self._save_planning_refusal(
                    task,
                    diagnostic,
                    retrieval,
                    planning_assets.manifest_hash,
                    refusal_code="CURRENT_PARAMETER_STATE_INVALID",
                    refusal_message="当前 Batch 参数状态格式无效。",
                    supporting_evidence=(str(error),),
                    constraint_snapshot_version=snapshot.snapshot_version,
                )
            if len(values) != 1:
                return self._save_planning_refusal(
                    task,
                    diagnostic,
                    retrieval,
                    planning_assets.manifest_hash,
                    refusal_code="CURRENT_PARAMETER_STATE_INCONSISTENT",
                    refusal_message="当前 Batch 参数值不一致，无法形成单一安全基线。",
                    supporting_evidence=(f"parameter_name={name}",),
                    constraint_snapshot_version=snapshot.snapshot_version,
                )
            current_values[name] = str(next(iter(values)))
        current_value_refusal = validate_current_parameter_values(
            current_values, snapshot
        )
        if current_value_refusal is not None:
            return self._save_planning_refusal(
                task,
                diagnostic,
                retrieval,
                planning_assets.manifest_hash,
                refusal_code=current_value_refusal,
                refusal_message="当前参数未通过范围、精度或步长网格校验。",
                supporting_evidence=tuple(
                    f"{name}={value}" for name, value in sorted(current_values.items())
                ),
                constraint_snapshot_version=snapshot.snapshot_version,
            )
        if diagnostic.anomaly_result != AnomalyResult.TARGET_ANOMALY.value:
            return self._save_planning_refusal(
                task,
                diagnostic,
                retrieval,
                planning_assets.manifest_hash,
                refusal_code="ANOMALY_RESULT_NOT_TARGET",
                refusal_message="仅 TARGET_ANOMALY 可生成参数候选。",
                supporting_evidence=(f"anomaly_result={diagnostic.anomaly_result}",),
                constraint_snapshot_version=snapshot.snapshot_version,
            )
        if diagnostic.evidence_status != "SUFFICIENT_EVIDENCE":
            return self._save_planning_refusal(
                task,
                diagnostic,
                retrieval,
                planning_assets.manifest_hash,
                refusal_code="INSUFFICIENT_EVIDENCE",
                refusal_message="当前诊断证据不足，未生成参数候选。",
                supporting_evidence=tuple(
                    f"{item.rule_id}:{item.status}" for item in diagnostic.evidence_checks
                ),
                constraint_snapshot_version=snapshot.snapshot_version,
            )
        if len(diagnostic.ordered_top3) != 3 or diagnostic.ordered_top3[0].rank != 1:
            return self._save_planning_refusal(
                task,
                diagnostic,
                retrieval,
                planning_assets.manifest_hash,
                refusal_code="DIAGNOSTIC_TOP1_INVALID",
                refusal_message="诊断 Top-3 或 Top-1 结构无效。",
                supporting_evidence=(),
                constraint_snapshot_version=snapshot.snapshot_version,
            )
        top1 = diagnostic.ordered_top3[0].root_cause
        inspection_actions = self._inspection_actions(top1)
        if inspection_actions:
            return self._save_planning_refusal(
                task,
                diagnostic,
                retrieval,
                planning_assets.manifest_hash,
                refusal_code=f"{top1}_INSPECTION_ONLY",
                refusal_message="当前 Top-1 属于不可调故障，仅输出结构化排查建议。",
                supporting_evidence=(f"top1_root_cause={top1}",),
                recommended_inspection_actions=inspection_actions,
                constraint_snapshot_version=snapshot.snapshot_version,
            )
        if top1 == "Z_DEFOCUS_CONDITIONAL" and not diagnostic.z_gate_result.passed:
            return self._save_planning_refusal(
                task,
                diagnostic,
                retrieval,
                planning_assets.manifest_hash,
                refusal_code="Z_GATE_NOT_PASSED",
                refusal_message="Z_DEFOCUS_CONDITIONAL 方向门控未通过。",
                supporting_evidence=tuple(
                    f"{item.rule_id}:{item.status}"
                    for item in diagnostic.z_gate_result.checks
                ),
                constraint_snapshot_version=snapshot.snapshot_version,
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
            snapshot=snapshot,
            diagnostic_result_version=diagnostic.diagnostic_result_version,
            feature_definition_version=diagnostic.feature_definition_version,
            z_gate_passed=diagnostic.z_gate_result.passed,
        )
        if not direction.usable_evidence:
            refusal_code = (
                "DIRECTION_RULE_CONFLICT"
                if any(
                    item.conflict_status == "CONFLICT"
                    for item in direction.direction_evidence
                )
                else direction.refusal_code or "NO_CLEAR_DIRECTION_EVIDENCE"
            )
            return self._save_planning_refusal(
                task,
                diagnostic,
                retrieval,
                planning_assets.manifest_hash,
                refusal_code=refusal_code,
                refusal_message="没有参数形成可用且无冲突的方向证据。",
                supporting_evidence=tuple(
                    f"{item.parameter_name}:{item.conflict_status}"
                    for item in direction.direction_evidence
                ),
                direction_evidence=direction.direction_evidence,
                constraint_snapshot_version=snapshot.snapshot_version,
            )
        try:
            historical_cases, case_index_hash, case_asset_manifest_hash = self._planning_cases(
                task, retrieval
            )
        except (ParameterPlanningAssetError, ParameterPlanningGuardError) as error:
            self._raise_planning_guard(
                task,
                diagnostic_result_id,
                case_retrieval_result_id,
                error.code,
                error.message,
                status_code=error.status_code,
            )
        parameter_family = planning_assets.safety_policy.family_for_root_cause(top1)
        if parameter_family is None:
            return self._save_planning_refusal(
                task,
                diagnostic,
                retrieval,
                planning_assets.manifest_hash,
                refusal_code="TOP1_PARAMETER_FAMILY_NOT_ALLOWED",
                refusal_message="Top-1 不属于版本化规则允许的参数族。",
                supporting_evidence=(f"top1_root_cause={top1}",),
                constraint_snapshot_version=snapshot.snapshot_version,
            )
        generated = ParameterPlanGenerator(
            validator=ParameterSafetyValidator(planning_assets.safety_policy),
            planning_policy=planning_assets.planning_policy,
        ).generate(
            root_cause=top1,
            parameter_family=parameter_family,
            current_values=current_values,
            direction_evidence=direction.usable_evidence,
            snapshot=snapshot,
            diagnostic_result_version=diagnostic.diagnostic_result_version,
            case_retrieval_result_version=(
                None if retrieval is None else retrieval.retrieval_result_version
            ),
            cases=historical_cases,
            feature_definition_version=diagnostic.feature_definition_version,
            product_model=task.data_import.product_model,
        )
        input_bindings = {
            "task_id": task.task_id,
            "diagnostic_result_id": diagnostic.diagnostic_result_id,
            "diagnostic_result_hash": diagnostic.result_hash,
            "case_retrieval_result_id": (
                None if retrieval is None else retrieval.retrieval_result_id
            ),
            "case_retrieval_result_hash": (
                None if retrieval is None else retrieval.result_hash
            ),
            "measurement_hash": current_observation_hash,
            "feature_hash": features.input_feature_hash,
            "parameter_constraint_snapshot_hash": snapshot_hash,
            "planning_asset_manifest_hash": planning_assets.manifest_hash,
            "case_index_hash": case_index_hash,
            "case_asset_manifest_hash": case_asset_manifest_hash,
            "historical_case_ids": tuple(case.case_id for case in historical_cases),
        }
        if not generated.ordered_candidates:
            return self._save_planning_refusal(
                task,
                diagnostic,
                retrieval,
                planning_assets.manifest_hash,
                refusal_code="ALL_CANDIDATES_REJECTED",
                refusal_message="所有候选均被 ParameterSafetyValidator 拒绝。",
                supporting_evidence=tuple(
                    reason
                    for item in generated.rejected_candidates
                    for reason in item.rejection_reasons
                ),
                direction_evidence=direction.direction_evidence,
                case_guidance_status=generated.case_guidance_status,
                constraint_snapshot_version=snapshot.snapshot_version,
                input_bindings=input_bindings,
            )
        record = record_parameter_planning(
            task_id=task.task_id,
            diagnostic_result_id=diagnostic.diagnostic_result_id,
            case_retrieval_result_id=(
                None if retrieval is None else retrieval.retrieval_result_id
            ),
            top1_root_cause=top1,
            direction_evidence=direction.direction_evidence,
            ordered_candidates=generated.ordered_candidates,
            parameter_constraints=snapshot.constraints,
            planning_status="CANDIDATES_AVAILABLE",
            refusal_code=None,
            refusal_message=None,
            supporting_evidence=(
                f"usable_direction_evidence={len(direction.usable_evidence)}",
                f"passed_candidate_count={len(generated.ordered_candidates)}",
            ),
            recommended_inspection_actions=(),
            case_guidance_status=generated.case_guidance_status,
            input_bindings=input_bindings,
            constraint_snapshot_version=snapshot.snapshot_version,
            rule_set_version=task.versions.rule_set_version,
            feature_definition_version=diagnostic.feature_definition_version,
            diagnostic_result_version=diagnostic.diagnostic_result_version,
            case_retrieval_result_version=(
                None if retrieval is None else retrieval.retrieval_result_version
            ),
            planning_asset_manifest_hash=planning_assets.manifest_hash,
            created_at=self._clock.now(),
        )
        updated_task = replace(
            task,
            status=TaskStatus.PLAN_READY,
            stages=workflow_for(TaskStatus.PLAN_READY),
            parameter_planning_result=record,
        )
        try:
            return self._store.save_parameter_planning(updated_task, record)
        except ParameterPlanningResultConflictError as error:
            raise ParameterPlanningGuardError(
                "PARAMETER_PLANNING_RESULT_CONFLICT",
                "当前任务的参数规划结果已发生冲突。",
            ) from error

    def _raise_planning_guard(
        self,
        task: Task,
        requested_diagnostic_result_id: str,
        requested_case_retrieval_result_id: str | None,
        code: str,
        message: str,
        *,
        status_code: int = 409,
        supporting_evidence: tuple[str, ...] = (),
        recommended_inspection_actions: tuple[str, ...] = (),
    ) -> Never:
        record = record_parameter_planning_refusal(
            task_id=task.task_id,
            requested_diagnostic_result_id=requested_diagnostic_result_id,
            requested_case_retrieval_result_id=requested_case_retrieval_result_id,
            refusal_code=code,
            refusal_message=message,
            supporting_evidence=supporting_evidence,
            recommended_inspection_actions=recommended_inspection_actions,
            rule_set_version=task.versions.rule_set_version,
            created_at=self._clock.now(),
        )
        self._store.save_parameter_planning_refusal(record)
        raise ParameterPlanningGuardError(
            code,
            message,
            status_code,
            supporting_evidence=supporting_evidence,
            recommended_inspection_actions=recommended_inspection_actions,
            rule_set_version=task.versions.rule_set_version,
        )

    def _validated_current_planning(
        self,
        task: Task,
        current: ParameterPlanningResultRecord,
    ) -> tuple[Task, ParameterPlanningResultRecord]:
        if self._planning_asset_root is None or self._expected_planning_manifest_hash is None:
            self._raise_planning_guard(
                task,
                current.diagnostic_result_id,
                current.case_retrieval_result_id,
                "PLANNING_ASSETS_MISSING",
                "固定参数规划规则资产未装配。",
            )
        try:
            planning_assets = ParameterPlanningAssetLoader(
                self._planning_asset_root,
                self._expected_planning_manifest_hash,
            ).load()
        except ParameterPlanningAssetError as error:
            self._raise_planning_guard(
                task,
                current.diagnostic_result_id,
                current.case_retrieval_result_id,
                error.code,
                error.message,
                status_code=error.status_code,
            )
        if (
            current.planning_asset_manifest_hash != planning_assets.manifest_hash
            or current.rule_set_version != task.versions.rule_set_version
        ):
            self._raise_planning_guard(
                task,
                current.diagnostic_result_id,
                current.case_retrieval_result_id,
                "PARAMETER_PLANNING_RULES_STALE",
                "当前参数规划结果绑定的规则资产已过期。",
            )
        diagnostic = task.diagnostic_result
        if diagnostic is None:
            self._raise_planning_guard(
                task,
                current.diagnostic_result_id,
                current.case_retrieval_result_id,
                "PARAMETER_PLANNING_DIAGNOSTIC_STALE",
                "当前参数规划结果绑定的诊断已缺失。",
            )
        try:
            self._validate_diagnostic_for_retrieval(task, diagnostic)
        except CaseRetrievalGuardError as error:
            self._raise_planning_guard(
                task,
                current.diagnostic_result_id,
                current.case_retrieval_result_id,
                "PARAMETER_PLANNING_DIAGNOSTIC_STALE",
                "当前参数规划结果绑定的诊断已过期。",
                supporting_evidence=(f"diagnostic_guard={error.code}",),
            )
        retrieval = self._store.get_current_case_retrieval(task.task_id)
        if (
            diagnostic.diagnostic_result_id != current.diagnostic_result_id
            or (None if retrieval is None else retrieval.retrieval_result_id)
            != current.case_retrieval_result_id
        ):
            self._raise_planning_guard(
                task,
                current.diagnostic_result_id,
                current.case_retrieval_result_id,
                "PARAMETER_PLANNING_INPUT_STALE",
                "当前诊断或案例检索引用已变化。",
            )
        source = self._store.get_planning_input(task.task_id)
        if (
            source.parameter_constraints is None
            or source.control_limits is None
            or not source.measurements
            or task.data_import is None
        ):
            self._raise_planning_guard(
                task,
                current.diagnostic_result_id,
                current.case_retrieval_result_id,
                "PLANNING_INPUT_OR_SNAPSHOT_MISSING",
                "当前参数规划输入或快照已缺失。",
            )
        try:
            snapshot = ParameterConstraintSnapshot.from_payload(
                source.parameter_constraints
            )
        except (KeyError, TypeError, ValueError) as error:
            self._raise_planning_guard(
                task,
                current.diagnostic_result_id,
                current.case_retrieval_result_id,
                "PARAMETER_CONSTRAINT_SNAPSHOT_INVALID",
                "参数约束快照格式无效。",
                supporting_evidence=(str(error),),
            )
        snapshot_hash = hashlib.sha256(
            (
                json.dumps(
                    source.parameter_constraints,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            ).encode("utf-8")
        ).hexdigest()
        if (
            snapshot_hash
            != planning_assets.expected_parameter_constraint_snapshot_hash
            or snapshot.snapshot_version != current.constraint_snapshot_version
            or source.control_limits.get("snapshot_version")
            != task.data_import.snapshot_versions.control_limit_snapshot
            or source.control_limits.get("rule_set_version")
            != task.versions.rule_set_version
        ):
            self._raise_planning_guard(
                task,
                current.diagnostic_result_id,
                current.case_retrieval_result_id,
                "PLANNING_SNAPSHOT_OR_RULE_TAMPERED",
                "控制限、参数快照或规则内容已变化。",
                supporting_evidence=(
                    f"parameter_constraint_snapshot_hash={snapshot_hash}",
                ),
            )
        measurement_hash = canonical_measurement_hash(source.measurements)
        features = FeatureEngineer().derive(source.measurements)
        if (
            measurement_hash != task.data_import.hashes.canonical_observation_hash
            or features.input_feature_hash != diagnostic.input_feature_hash
        ):
            self._raise_planning_guard(
                task,
                current.diagnostic_result_id,
                current.case_retrieval_result_id,
                "PARAMETER_PLANNING_DIAGNOSTIC_STALE",
                "当前 Measurement 或 DerivedFeatureSet 已变化。",
            )
        current_values: dict[str, str] = {}
        for name in PARAMETER_FIELDS:
            try:
                values = {Decimal(row[name]) for row in source.measurements}
            except (KeyError, InvalidOperation, TypeError) as error:
                self._raise_planning_guard(
                    task,
                    current.diagnostic_result_id,
                    current.case_retrieval_result_id,
                    "CURRENT_PARAMETER_STATE_INVALID",
                    "当前参数状态格式无效。",
                    supporting_evidence=(str(error),),
                )
            if len(values) != 1:
                self._raise_planning_guard(
                    task,
                    current.diagnostic_result_id,
                    current.case_retrieval_result_id,
                    "CURRENT_PARAMETER_STATE_INCONSISTENT",
                    "当前参数状态不一致。",
                    supporting_evidence=(f"parameter_name={name}",),
                )
            current_values[name] = str(next(iter(values)))
        current_value_refusal = validate_current_parameter_values(
            current_values, snapshot
        )
        if current_value_refusal is not None:
            self._raise_planning_guard(
                task,
                current.diagnostic_result_id,
                current.case_retrieval_result_id,
                current_value_refusal,
                "当前参数未通过范围、精度或步长网格复核。",
            )
        try:
            historical_cases, case_index_hash, case_asset_manifest_hash = self._planning_cases(
                task, retrieval
            )
        except (ParameterPlanningAssetError, ParameterPlanningGuardError) as error:
            self._raise_planning_guard(
                task,
                current.diagnostic_result_id,
                current.case_retrieval_result_id,
                error.code,
                error.message,
                status_code=error.status_code,
            )
        input_bindings = {
            "task_id": task.task_id,
            "diagnostic_result_id": diagnostic.diagnostic_result_id,
            "diagnostic_result_hash": diagnostic.result_hash,
            "case_retrieval_result_id": (
                None if retrieval is None else retrieval.retrieval_result_id
            ),
            "case_retrieval_result_hash": (
                None if retrieval is None else retrieval.result_hash
            ),
            "measurement_hash": measurement_hash,
            "feature_hash": features.input_feature_hash,
            "parameter_constraint_snapshot_hash": snapshot_hash,
            "planning_asset_manifest_hash": planning_assets.manifest_hash,
            "case_index_hash": case_index_hash,
            "case_asset_manifest_hash": case_asset_manifest_hash,
            "historical_case_ids": tuple(case.case_id for case in historical_cases),
        }
        if current.planning_status != "CANDIDATES_AVAILABLE":
            if (
                current.refusal_code == "ALL_CANDIDATES_REJECTED"
                and current.input_hash
                != parameter_planning_input_hash(input_bindings)
            ):
                self._raise_planning_guard(
                    task,
                    current.diagnostic_result_id,
                    current.case_retrieval_result_id,
                    "PARAMETER_PLANNING_INPUT_STALE",
                    "当前结构化拒绝所绑定的输入哈希已变化。",
                )
            return task, current
        if current.input_hash != parameter_planning_input_hash(input_bindings):
            self._raise_planning_guard(
                task,
                current.diagnostic_result_id,
                current.case_retrieval_result_id,
                "PARAMETER_PLANNING_INPUT_STALE",
                "当前参数规划输入哈希已变化。",
            )
        validator = ParameterSafetyValidator(planning_assets.safety_policy)
        for candidate in current.ordered_candidates:
            validation = validator.validate(
                candidate,
                snapshot=snapshot,
                versions=SafetyVersionContext(
                    constraint_snapshot_version=snapshot.snapshot_version,
                    rule_set_version=snapshot.rule_set_version,
                    direction_rule_version=planning_assets.direction_rules.direction_rule_version,
                    safety_rule_version=planning_assets.safety_policy.safety_rule_version,
                    diagnostic_result_version=diagnostic.diagnostic_result_version,
                    case_retrieval_result_version=(
                        None
                        if retrieval is None
                        else retrieval.retrieval_result_version
                    ),
                ),
            )
            if (
                validation.validation_status != "PASSED"
                or candidate.current_values
                != {
                    name: f"{Decimal(value):.6f}"
                    for name, value in sorted(current_values.items())
                }
            ):
                self._raise_planning_guard(
                    task,
                    current.diagnostic_result_id,
                    current.case_retrieval_result_id,
                    "PARAMETER_PLANNING_CANDIDATE_STALE",
                    "已保存候选未通过当前统一安全复核。",
                    supporting_evidence=validation.rejection_reasons,
                )
        return task, current

    def _planning_cases(
        self,
        task: Task,
        retrieval: CaseRetrievalResultRecord | None,
    ) -> tuple[tuple[HistoricalCaseAction, ...], str | None, str | None]:
        if retrieval is None:
            return (), None, None
        if self._case_asset_root is None or self._expected_case_manifest_hash is None:
            raise ParameterPlanningAssetError(
                "CASE_ASSETS_MISSING", "案例引导所需 APPROVED 资产未装配。"
            )
        assets = ApprovedCaseAssetLoader(
            self._case_asset_root, self._expected_case_manifest_hash
        ).load()
        if (
            retrieval.case_index_hash != assets.index_file_hash
            or retrieval.case_index_version != assets.case_index_version
            or retrieval.scaler_version != assets.scaler_version
            or retrieval.compatibility_rule_version
            != assets.compatibility_rule_version
            or retrieval.retrieval_rule_version != assets.retrieval_rule_version
        ):
            raise ParameterPlanningGuardError(
                "PARAMETER_PLANNING_RETRIEVAL_STALE",
                "案例检索结果与当前案例索引或规则版本不一致。",
            )
        by_id = {case.case_id: case for case in assets.cases}
        converted: list[HistoricalCaseAction] = []
        for retrieved in retrieval.ordered_cases:
            case = by_id.get(retrieved.case_id)
            if case is None or case.parameter_family is None:
                continue
            action = case.historical_action
            result = case.historical_simulated_result
            converted.append(
                HistoricalCaseAction(
                    case_id=case.case_id,
                    status=case.status,
                    source_partition=case.source_partition,
                    source_partition_id=case.source_partition_id,
                    station_type=case.station_type,
                    product_model=case.product_model,
                    reviewed_root_cause=case.reviewed_root_cause,
                    parameter_family=case.parameter_family,
                    parameter_delta_ticks=dict(action["parameter_delta_ticks"]),
                    action_version=action["action_version"],
                    historical_safety_status=action["historical_safety_status"],
                    historical_safety_rule_version=action[
                        "historical_safety_rule_version"
                    ],
                    historical_simulated_result_status=result["status"],
                    center_within_tolerance=result["center_within_tolerance"],
                    feature_definition_version=case.feature_definition_version,
                    rule_set_version=case.rule_set_version,
                    retrieval_rule_version=case.retrieval_rule_version,
                    case_schema_version=case.case_schema_version,
                )
            )
        return tuple(converted), assets.index_file_hash, assets.manifest_hash

    def _save_planning_refusal(
        self,
        task: Task,
        diagnostic: DiagnosticResultRecord,
        retrieval: CaseRetrievalResultRecord | None,
        planning_asset_manifest_hash: str,
        *,
        refusal_code: str,
        refusal_message: str,
        supporting_evidence: tuple[str, ...],
        recommended_inspection_actions: tuple[str, ...] = (),
        direction_evidence: tuple = (),
        case_guidance_status: str = "NO_COMPATIBLE_APPROVED_CASE",
        constraint_snapshot_version: str | None = None,
        input_bindings: dict[str, object] | None = None,
    ) -> tuple[Task, ParameterPlanningResultRecord]:
        top1 = (
            diagnostic.ordered_top3[0].root_cause
            if diagnostic.ordered_top3
            else "UNAVAILABLE"
        )
        record = record_parameter_planning(
            task_id=task.task_id,
            diagnostic_result_id=diagnostic.diagnostic_result_id,
            case_retrieval_result_id=(
                None if retrieval is None else retrieval.retrieval_result_id
            ),
            top1_root_cause=top1,
            direction_evidence=direction_evidence,
            ordered_candidates=(),
            parameter_constraints=(),
            planning_status="PARAMETER_RECOMMENDATION_REFUSED",
            refusal_code=refusal_code,
            refusal_message=refusal_message,
            supporting_evidence=supporting_evidence,
            recommended_inspection_actions=recommended_inspection_actions,
            case_guidance_status=case_guidance_status,
            input_bindings=input_bindings
            or {
                "task_id": task.task_id,
                "diagnostic_result_hash": diagnostic.result_hash,
                "case_retrieval_result_hash": (
                    None if retrieval is None else retrieval.result_hash
                ),
                "refusal_code": refusal_code,
                "planning_asset_manifest_hash": planning_asset_manifest_hash,
            },
            constraint_snapshot_version=(
                constraint_snapshot_version
                or (
                    task.data_import.snapshot_versions.parameter_constraint_snapshot
                    if task.data_import is not None
                    else "MISSING"
                )
            ),
            rule_set_version=task.versions.rule_set_version,
            feature_definition_version=diagnostic.feature_definition_version,
            diagnostic_result_version=diagnostic.diagnostic_result_version,
            case_retrieval_result_version=(
                None if retrieval is None else retrieval.retrieval_result_version
            ),
            planning_asset_manifest_hash=planning_asset_manifest_hash,
            created_at=self._clock.now(),
        )
        updated_task = replace(task, parameter_planning_result=record)
        try:
            return self._store.save_parameter_planning(updated_task, record)
        except ParameterPlanningResultConflictError as error:
            raise ParameterPlanningGuardError(
                "PARAMETER_PLANNING_RESULT_CONFLICT",
                "当前任务的结构化参数规划拒绝结果已发生冲突。",
            ) from error

    @staticmethod
    def _inspection_actions(root_cause: str) -> tuple[str, ...]:
        return {
            "PLATFORM_INSTABILITY": (
                "检查重复定位误差",
                "检查振动或回差证据",
                "复核平台稳定性",
            ),
            "REFERENCE_DRIFT": (
                "检查夹具基准",
                "复核标定残差",
                "执行受控标定检查",
            ),
        }.get(root_cause, ())

    @staticmethod
    def _validate_diagnostic_for_retrieval(
        task: Task,
        diagnostic: DiagnosticResultRecord,
    ) -> None:
        detection = task.anomaly_detection
        if detection is None or diagnostic.detection_result_id != detection.detection_result_id:
            raise CaseRetrievalGuardError(
                "CASE_RETRIEVAL_DIAGNOSTIC_STALE",
                "诊断结果引用的异常检测不是当前版本。",
            )
        data_import = task.data_import
        if data_import is None:
            raise CaseRetrievalGuardError(
                "CASE_RETRIEVAL_BATCH_MISSING", "当前任务缺少已导入 Batch。"
            )
        if (
            detection.input_data_version != task.versions.dataset_version
            or detection.input_hash
            != data_import.hashes.canonical_observation_hash
            or detection.rule_set_version != task.versions.rule_set_version
            or detection.control_limit_snapshot_version
            != data_import.snapshot_versions.control_limit_snapshot
        ):
            raise CaseRetrievalGuardError(
                "CASE_RETRIEVAL_DIAGNOSTIC_STALE",
                "诊断引用的检测结果与当前可观测输入或版本快照不一致。",
            )
        if diagnostic.anomaly_result != AnomalyResult.TARGET_ANOMALY.value:
            raise CaseRetrievalGuardError(
                "CASE_RETRIEVAL_ANOMALY_NOT_TARGET",
                "只有 TARGET_ANOMALY 诊断结果可以检索案例。",
            )
        if (
            diagnostic.diagnostic_result_version != DIAGNOSTIC_RESULT_VERSION
            or diagnostic.task_id != task.task_id
            or diagnostic.input_data_version != task.versions.dataset_version
            or diagnostic.model_version != task.versions.model_version
            or diagnostic.preprocessing_version != task.versions.preprocessing_version
            or diagnostic.feature_definition_version != FEATURE_DEFINITION_VERSION
            or diagnostic.evidence_rule_version != EVIDENCE_RULE_VERSION
        ):
            raise CaseRetrievalGuardError(
                "CASE_RETRIEVAL_DIAGNOSTIC_VERSION_STALE",
                "当前诊断结果的输入、模型或特征定义版本已过期。",
            )
        business_payload = asdict(diagnostic)
        business_payload.pop("diagnostic_result_id")
        business_payload.pop("result_hash")
        business_payload.pop("created_at")
        expected_hash = hashlib.sha256(
            json.dumps(
                business_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        if (
            diagnostic.result_hash != expected_hash
            or diagnostic.diagnostic_result_id
            != f"tw-diagnostic-{expected_hash[:16]}"
        ):
            raise CaseRetrievalGuardError(
                "CASE_RETRIEVAL_DIAGNOSTIC_INVALID",
                "当前诊断结果内容哈希无效。",
            )

    def _validated_detection_input(
        self,
        task: Task,
        source: StoredDetectionInput,
    ) -> DetectionInput:
        if source.manifest is None or source.batch is None:
            raise DetectionGuardError(
                "DETECTION_INPUT_MISSING",
                "当前任务缺少 Batch 或 DatasetManifest。",
            )
        if source.control_limits is None or source.spc_rules is None:
            raise DetectionGuardError(
                "DETECTION_SNAPSHOT_MISSING",
                "当前任务缺少控制限或版本化 SPC 规则快照。",
            )
        manifest = source.manifest
        data_import = task.data_import
        if data_import is None:
            raise DetectionGuardError(
                "DETECTION_INPUT_MISSING", "当前任务缺少导入结果。"
            )
        if (
            self._expected_dataset_manifest_hash is None
            or manifest.get("dataset_manifest_hash")
            != self._expected_dataset_manifest_hash
        ):
            raise DetectionGuardError(
                "DETECTION_MANIFEST_HASH_MISMATCH",
                "持久化 DatasetManifest 与受信任清单哈希不一致。",
            )
        expected_versions = {
            "canonicalizer_version": task.versions.canonicalizer_version,
            "dataset_version": task.versions.dataset_version,
            "evaluation_rule_version": task.versions.evaluation_rule_version,
            "generator_version": task.versions.generator_version,
            "model_version": task.versions.model_version,
            "preprocessing_version": task.versions.preprocessing_version,
            "rule_set_version": task.versions.rule_set_version,
            "schema_version": task.versions.schema_version,
        }
        if manifest.get("versions") != expected_versions:
            raise DetectionGuardError(
                "DETECTION_MANIFEST_VERSION_STALE",
                "DatasetManifest 版本不是当前任务快照。",
            )
        if (
            manifest.get("batch_id") != data_import.batch_id
            or source.batch.get("batch_id") != data_import.batch_id
            or manifest.get("raw_file_hash") != data_import.hashes.raw_file_hash
            or manifest.get("canonical_observation_hash")
            != data_import.hashes.canonical_observation_hash
        ):
            raise DetectionGuardError(
                "DETECTION_INPUT_VERSION_STALE",
                "导入结果不是当前任务最新数据版本。",
            )
        actual_input_hash = canonical_measurement_hash(source.measurements)
        if actual_input_hash != data_import.hashes.canonical_observation_hash:
            raise DetectionGuardError(
                "DETECTION_INPUT_HASH_MISMATCH",
                "持久化 Measurement 与导入输入哈希不一致。",
            )
        try:
            controls = ControlLimitSnapshot(
                snapshot_version=source.control_limits["snapshot_version"],
                rule_set_version=source.control_limits["rule_set_version"],
                center_lower_limit=Decimal(
                    source.control_limits["center_lower_limit"]
                ),
                corner_lower_limit=Decimal(
                    source.control_limits["corner_lower_limit"]
                ),
                asymmetry_limit=Decimal(
                    source.control_limits["asymmetry_limit"]
                ),
                corner_std_limit=Decimal(
                    source.control_limits["corner_std_limit"]
                ),
            )
            spc_rules = deserialize_spc_rule_snapshot(source.spc_rules)
        except (KeyError, TypeError, ValueError, InvalidOperation) as error:
            raise DetectionGuardError(
                "DETECTION_SNAPSHOT_INVALID",
                "控制限或 SPC 规则快照格式无效。",
            ) from error
        if (
            controls.rule_set_version != task.versions.rule_set_version
            or spc_rules.rule_set_version != task.versions.rule_set_version
        ):
            raise DetectionGuardError(
                "DETECTION_RULE_VERSION_STALE",
                "控制限或 SPC 规则版本不是当前任务版本。",
            )
        try:
            expected_rules = SpcRuleRegistry.snapshot_for(
                task.versions.rule_set_version
            )
        except KeyError as error:
            raise DetectionGuardError(
                "DETECTION_RULE_VERSION_UNSUPPORTED",
                "当前 SPC 规则版本不受支持。",
            ) from error
        if spc_rules != expected_rules:
            raise DetectionGuardError(
                "DETECTION_RULE_SNAPSHOT_INVALID",
                "SPC 规则快照内容与冻结版本不一致。",
            )
        try:
            expected_controls = ControlLimitRegistry.snapshot_for(
                task.versions.rule_set_version
            )
        except KeyError as error:
            raise DetectionGuardError(
                "DETECTION_RULE_VERSION_UNSUPPORTED",
                "当前控制限规则版本不受支持。",
            ) from error
        if controls != expected_controls:
            raise DetectionGuardError(
                "DETECTION_CONTROL_SNAPSHOT_INVALID",
                "控制限快照内容与冻结版本不一致。",
            )
        if (
            controls.snapshot_version
            != data_import.snapshot_versions.control_limit_snapshot
        ):
            raise DetectionGuardError(
                "DETECTION_CONTROL_SNAPSHOT_STALE",
                "控制限快照不是任务导入时版本。",
            )
        return DetectionInput(
            task_id=task.task_id,
            batch_id=data_import.batch_id,
            measurements=source.measurements,
            control_limits=controls,
            rule_snapshot=spc_rules,
            input_data_version=task.versions.dataset_version,
            input_hash=actual_input_hash,
        )
