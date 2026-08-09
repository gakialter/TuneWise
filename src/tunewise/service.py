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
    CASE_INDEX_VERSION,
    CASE_SCHEMA_VERSION,
    COMPATIBILITY_RULE_VERSION,
    RETRIEVAL_RULE_VERSION,
    SCALER_VERSION,
    ApprovedCaseAssetLoader,
    CaseRetrievalAssetError,
    CaseRetrievalGuardError,
    CaseRetrievalResultRecord,
    StructuredCaseRetriever,
    record_case_retrieval,
)
from .domain import Task, TaskStatus, workflow_for
from .device_execution import (
    DeviceExecutionQualification,
    DeviceQualificationError,
)
from .detection import (
    DETECTION_RESULT_VERSION,
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
    DiagnosticAssetError,
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
    candidate_content_hash,
)
from .plan_confirmation import (
    AuditEvent,
    ConfirmedPlan,
    ConfirmedPlanFreshnessEvaluator,
    FreshnessBinding,
    PlanConfirmationGuardError,
    canonical_hash,
    create_audit_event,
    create_confirmed_plan,
    confirmed_plan_business_payload,
)
from .replay import (
    ReplayBoundaryAudit,
    ReplayComputation,
    ReplayEvaluationRuleSnapshot,
    ReplayGuardError,
    ReplayOrchestrator,
    ReplayResult,
    create_replay_result,
)
from .store import (
    CaseRetrievalResultConflictError,
    DiagnosticResultConflictError,
    DetectionResultConflictError,
    ImportSnapshotConflictError,
    StoredDetectionInput,
    StoredReplayInput,
    TaskStore,
    ParameterPlanningResultConflictError,
    ConfirmedPlanConflictError,
    ConfirmationStateChangedError,
    ReplayResultConflictError,
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
        replay_asset_root: Path | None = None,
        expected_replay_manifest_hash: str | None = None,
        replay_boundary_audit: ReplayBoundaryAudit | None = None,
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
        self._replay_boundary_audit = replay_boundary_audit or ReplayBoundaryAudit()
        self._replay_orchestrator = (
            None
            if replay_asset_root is None or expected_replay_manifest_hash is None
            else ReplayOrchestrator(
                replay_asset_root,
                expected_replay_manifest_hash,
                self._replay_boundary_audit,
            )
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
        stored = self._store.get_or_create(task)
        if stored.actor != assets.actor or stored.versions != assets.versions:
            raise AssetIntegrityError(
                "TASK_ASSET_SNAPSHOT_MISMATCH",
                "任务绑定的公共版本快照与当前资产不一致。",
            )
        if stored.confirmed_plan is not None:
            stored = self._refresh_confirmed_plan(stored)
        return stored

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
        if task is not None and task.confirmed_plan is not None:
            stored_plan = self._store.get_current_confirmed_plan(task.task_id)
            if (
                stored_plan is None
                or stored_plan.confirmed_plan_id
                != task.confirmed_plan.confirmed_plan_id
                or stored_plan.confirmed_plan_hash
                != task.confirmed_plan.confirmed_plan_hash
            ):
                raise PlanConfirmationGuardError(
                    "CONFIRMED_PLAN_HASH_MISMATCH",
                    "任务与当前 ConfirmedPlan 的不可变绑定不一致。",
                )
            if stored_plan != task.confirmed_plan:
                task = replace(task, confirmed_plan=stored_plan)
            task = self._refresh_confirmed_plan(task)
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

    def confirm_parameter_plan(
        self,
        task_id: str,
        candidate_id: str,
        candidate_hash: str,
    ) -> tuple[Task, ConfirmedPlan]:
        self._planning_boundary_audit.assert_pristine()
        try:
            task = self.get_task(task_id)
        except ParameterPlanningGuardError as error:
            try:
                task = self._store.get_confirmation_task(task_id)
            except ConfirmationStateChangedError:
                task = None
            if task is None:
                raise PlanConfirmationGuardError(
                    "PLANNING_RESULT_STALE",
                    "任务内嵌 ParameterPlanningResult 无法安全读取。",
                ) from error
            self._raise_confirmation_guard(
                task,
                candidate_id,
                candidate_hash,
                "PLANNING_RESULT_STALE",
                "任务内嵌 ParameterPlanningResult 内容完整性校验失败。",
                actual_version=error.code,
            )
        if task is None:
            raise PlanConfirmationGuardError(
                "TASK_NOT_FOUND", "调机任务不存在。", 404
            )
        existing = self._store.get_current_confirmed_plan(task_id)
        if task.status is TaskStatus.PLAN_CONFIRMED:
            if existing is None:
                self._raise_confirmation_guard(
                    task,
                    candidate_id,
                    candidate_hash,
                    "CONFIRMED_PLAN_CONFLICT",
                    "任务已确认但缺少当前 ConfirmedPlan。",
                )
            if (
                existing.candidate_id == candidate_id
                and existing.candidate_hash == candidate_hash
                and existing.status == "VALID"
            ):
                return task, existing
            if (
                existing.candidate_id == candidate_id
                and existing.candidate_hash == candidate_hash
                and existing.status == "STALE"
            ):
                self._raise_confirmation_guard(
                    task,
                    candidate_id,
                    candidate_hash,
                    "CANDIDATE_STALE",
                    "已确认方案已过期，不能作为有效幂等确认结果返回。",
                )
            self._raise_confirmation_guard(
                task,
                candidate_id,
                candidate_hash,
                "CONFIRMED_PLAN_CONFLICT",
                "任务已确认其他候选，本票不允许改选方案。",
                expected_hash=existing.candidate_hash,
                actual_hash=candidate_hash,
            )
        if task.status is not TaskStatus.PLAN_READY:
            self._raise_confirmation_guard(
                task,
                candidate_id,
                candidate_hash,
                "TASK_NOT_PLAN_READY",
                "只有 PLAN_READY 任务可以人工确认候选。",
                actual_version=task.status.value,
                expected_version=TaskStatus.PLAN_READY.value,
            )
        try:
            initial_state_token = self._store.confirmation_state_token(task_id)
        except ConfirmationStateChangedError as error:
            self._raise_confirmation_guard(
                task,
                candidate_id,
                candidate_hash,
                "CANDIDATE_STALE",
                "确认状态投影格式无效或完整性校验失败。",
                actual_version=type(error.__cause__).__name__,
            )
        try:
            planning = self._store.get_current_parameter_planning(task_id)
        except ParameterPlanningGuardError as error:
            self._raise_confirmation_guard(
                task,
                candidate_id,
                candidate_hash,
                "PLANNING_RESULT_STALE",
                "当前 ParameterPlanningResult 内容完整性校验失败。",
                actual_version=error.code,
            )
        if planning is None:
            self._raise_confirmation_guard(
                task,
                candidate_id,
                candidate_hash,
                "PLANNING_RESULT_STALE",
                "当前任务缺少最新 ParameterPlanningResult。",
            )
        if planning.planning_status != "CANDIDATES_AVAILABLE":
            self._raise_confirmation_guard(
                task,
                candidate_id,
                candidate_hash,
                "PLANNING_RESULT_STALE",
                "当前参数规划结果没有可确认候选。",
                actual_version=planning.planning_status,
                expected_version="CANDIDATES_AVAILABLE",
            )
        candidate = next(
            (
                item
                for item in planning.ordered_candidates
                if item.candidate_id == candidate_id
            ),
            None,
        )
        if candidate is None:
            self._raise_confirmation_guard(
                task,
                candidate_id,
                candidate_hash,
                "CANDIDATE_NOT_FOUND",
                "candidate_id 不存在于当前最新参数规划结果。",
            )
        if candidate.validation_status != "PASSED":
            self._raise_confirmation_guard(
                task,
                candidate_id,
                candidate_hash,
                "CANDIDATE_NOT_PASSED",
                "只有 PASSED 候选可以人工确认。",
            )
        expected_candidate_hash = candidate_content_hash(candidate)
        if candidate.candidate_hash != expected_candidate_hash:
            self._raise_confirmation_guard(
                task,
                candidate_id,
                candidate_hash,
                "CANDIDATE_HASH_MISMATCH",
                "服务端候选规范化内容哈希不匹配。",
                expected_hash=expected_candidate_hash,
                actual_hash=candidate.candidate_hash,
            )
        if candidate_hash != candidate.candidate_hash:
            self._raise_confirmation_guard(
                task,
                candidate_id,
                candidate_hash,
                "CANDIDATE_HASH_MISMATCH",
                "请求 candidate_hash 与服务端当前候选不一致。",
                expected_hash=candidate.candidate_hash,
                actual_hash=candidate_hash,
            )
        try:
            binding, snapshot, planning_assets = self._confirmation_binding(
                task, planning, candidate
            )
        except (
            ParameterPlanningAssetError,
            CaseRetrievalAssetError,
            CaseRetrievalGuardError,
            ConfirmationStateChangedError,
            PlanConfirmationGuardError,
        ) as error:
            self._raise_confirmation_guard(
                task,
                candidate_id,
                candidate_hash,
                "CANDIDATE_STALE",
                "候选的当前版本、快照或受信任资产绑定已失效。",
                actual_version=getattr(error, "code", type(error).__name__),
            )
        validation = ParameterSafetyValidator(
            planning_assets.safety_policy
        ).validate(
            candidate,
            snapshot=snapshot,
            versions=SafetyVersionContext(
                constraint_snapshot_version=binding.parameter_constraint_snapshot_version,
                rule_set_version=binding.rule_set_version,
                direction_rule_version=binding.direction_rule_version,
                safety_rule_version=binding.safety_rule_version,
                diagnostic_result_version=binding.diagnostic_result_version,
                case_retrieval_result_version=binding.case_retrieval_result_version,
            ),
        )
        if validation.validation_status != "PASSED":
            self._raise_confirmation_guard(
                task,
                candidate_id,
                candidate_hash,
                "SAFETY_REVALIDATION_FAILED",
                "候选未通过确认阶段 ParameterSafetyValidator 复核。",
            )
        now = self._clock.now()
        plan = create_confirmed_plan(
            task_id=task_id,
            planning_result_id=planning.planning_result_id,
            planning_result_version=planning.planning_result_version,
            candidate=candidate,
            actor_id=task.actor.actor_id,
            actor_role=task.actor.actor_role,
            display_name=task.actor.display_name,
            confirmed_at=now,
            binding=binding,
        )
        try:
            final_binding, _final_snapshot, _final_assets = self._confirmation_binding(
                task, planning, candidate
            )
        except (
            ParameterPlanningAssetError,
            CaseRetrievalAssetError,
            CaseRetrievalGuardError,
            ConfirmationStateChangedError,
            PlanConfirmationGuardError,
        ) as error:
            self._raise_confirmation_guard(
                task,
                candidate_id,
                candidate_hash,
                "CANDIDATE_STALE",
                "确认提交点的版本、快照或受信任资产绑定已变化。",
                actual_version=getattr(error, "code", type(error).__name__),
            )
        try:
            final_state_token = self._store.confirmation_state_token(task_id)
        except ConfirmationStateChangedError as error:
            self._raise_confirmation_guard(
                task,
                candidate_id,
                candidate_hash,
                "CANDIDATE_STALE",
                "确认提交点的状态投影格式无效或完整性校验失败。",
                actual_version=type(error.__cause__).__name__,
            )
        try:
            include_case_assets = final_binding.case_retrieval_result_id is not None
            final_file_asset_token = self._confirmation_file_asset_token(
                include_case_assets=include_case_assets
            )
        except (
            ParameterPlanningAssetError,
            DiagnosticAssetError,
            CaseRetrievalAssetError,
            PlanConfirmationGuardError,
            FileNotFoundError,
        ) as error:
            self._raise_confirmation_guard(
                task,
                candidate_id,
                candidate_hash,
                "CANDIDATE_STALE",
                "确认提交点的受信任文件资产已变化。",
                actual_version=getattr(error, "code", type(error).__name__),
            )
        if final_binding != binding or final_state_token != initial_state_token:
            try:
                concurrent_task = self.get_task(task_id)
            except (
                AssetIntegrityError,
                ParameterPlanningGuardError,
                PlanConfirmationGuardError,
            ):
                concurrent_task = None
            concurrent = (
                None if concurrent_task is None else concurrent_task.confirmed_plan
            )
            if (
                concurrent is not None
                and concurrent.candidate_id == candidate_id
                and concurrent.candidate_hash == candidate_hash
                and concurrent.status == "VALID"
            ):
                return concurrent_task, concurrent
            if concurrent is not None:
                self._raise_confirmation_guard(
                    task,
                    candidate_id,
                    candidate_hash,
                    "CONFIRMED_PLAN_CONFLICT",
                    "并发确认已选择其他候选。",
                    expected_hash=concurrent.candidate_hash,
                    actual_hash=candidate_hash,
                )
            self._raise_confirmation_guard(
                task,
                candidate_id,
                candidate_hash,
                "CANDIDATE_STALE",
                "确认期间任务输入、快照、规则或资产已变化。",
            )
        freshness = ConfirmedPlanFreshnessEvaluator().evaluate(plan, final_binding)
        if freshness.status != "VALID":
            self._raise_confirmation_guard(
                task,
                candidate_id,
                candidate_hash,
                "CANDIDATE_STALE",
                "候选 freshness 复核失败。",
            )
        event = create_audit_event(
            task_id=task_id,
            actor_id=task.actor.actor_id,
            actor_role=task.actor.actor_role,
            display_name=task.actor.display_name,
            occurred_at=now,
            result="SUCCESS",
            rule_set_version=task.versions.rule_set_version,
            candidate_id=candidate_id,
            candidate_hash=candidate_hash,
            plan=plan,
        )
        updated_task = replace(
            task,
            status=TaskStatus.PLAN_CONFIRMED,
            stages=workflow_for(TaskStatus.PLAN_CONFIRMED),
            confirmed_plan=plan,
        )
        try:
            stored_task, stored_plan, _created = self._store.save_confirmation(
                updated_task,
                plan,
                event,
                expected_state_token=initial_state_token,
                expected_file_asset_token=final_file_asset_token,
                file_asset_token_reader=lambda: self._confirmation_file_asset_token(
                    include_case_assets=include_case_assets
                ),
            )
        except ConfirmationStateChangedError:
            try:
                current_task = self.get_task(task_id)
            except (
                AssetIntegrityError,
                ParameterPlanningGuardError,
                PlanConfirmationGuardError,
            ):
                current_task = None
            current = None if current_task is None else current_task.confirmed_plan
            if (
                current is not None
                and current.candidate_id == candidate_id
                and current.candidate_hash == candidate_hash
                and current.status == "VALID"
            ):
                return current_task, current
            if current is not None:
                self._raise_confirmation_guard(
                    task,
                    candidate_id,
                    candidate_hash,
                    "CONFIRMED_PLAN_CONFLICT",
                    "并发确认已选择其他候选。",
                    expected_hash=current.candidate_hash,
                    actual_hash=candidate_hash,
                )
            self._raise_confirmation_guard(
                task,
                candidate_id,
                candidate_hash,
                "CANDIDATE_STALE",
                "确认事务开始前任务输入、快照或当前结果已变化。",
            )
        except ConfirmedPlanConflictError as error:
            current = self._store.get_current_confirmed_plan(task_id)
            if (
                current is not None
                and current.candidate_id == candidate_id
                and current.candidate_hash == candidate_hash
            ):
                stored_task = self._store.get(task_id)
                if stored_task is not None:
                    return stored_task, current
            self._raise_confirmation_guard(
                task,
                candidate_id,
                candidate_hash,
                "CONFIRMED_PLAN_CONFLICT",
                "并发确认与当前已确认候选冲突。",
            )
        self._planning_boundary_audit.assert_pristine()
        return stored_task, stored_plan

    def record_confirmation_request_refusal(
        self,
        task_id: str,
        candidate_id: str | None,
        candidate_hash: str | None,
        forbidden_fields: tuple[str, ...],
    ) -> PlanConfirmationGuardError:
        task = self._store.get(task_id)
        error = PlanConfirmationGuardError(
            "FORBIDDEN_CONFIRMATION_FIELDS",
            "确认请求只允许提交 candidate_id 与 candidate_hash。",
            422,
        )
        if task is not None:
            self._record_confirmation_rejection(
                task,
                candidate_id,
                candidate_hash,
                error,
                actual_version=",".join(forbidden_fields),
            )
        return error

    def get_audit_events(self, task_id: str) -> tuple[AuditEvent, ...]:
        return self._store.get_audit_events(task_id)

    def _validate_replay_plan(
        self,
        task: Task,
        confirmed_plan_id: str,
        confirmed_plan_hash: str,
    ) -> ConfirmedPlan:
        plan = self._store.get_current_confirmed_plan(task.task_id)
        if plan is None or task.confirmed_plan is None:
            raise ReplayGuardError("CONFIRMED_PLAN_NOT_FOUND", "当前任务缺少 ConfirmedPlan。")
        if plan.confirmed_plan_id != confirmed_plan_id or plan.task_id != task.task_id:
            raise ReplayGuardError("CONFIRMED_PLAN_NOT_FOUND", "ConfirmedPlan 不属于当前任务。")
        recalculated_plan_hash = canonical_hash(confirmed_plan_business_payload(plan))
        if (
            confirmed_plan_hash != plan.confirmed_plan_hash
            or recalculated_plan_hash != plan.confirmed_plan_hash
        ):
            raise ReplayGuardError(
                "CONFIRMED_PLAN_HASH_MISMATCH",
                "请求或服务端 ConfirmedPlan 内容哈希不匹配。",
                expected_hash=plan.confirmed_plan_hash,
                actual_hash=confirmed_plan_hash,
            )
        if plan.status != "VALID":
            raise ReplayGuardError("CONFIRMED_PLAN_STALE", "STALE ConfirmedPlan 不得回放。")
        planning = self._store.get_current_parameter_planning(task.task_id)
        if planning is None:
            raise ReplayGuardError("CONFIRMED_PLAN_NOT_FRESH", "当前参数规划结果已缺失。")
        candidate = next(
            (item for item in planning.ordered_candidates if item.candidate_id == plan.candidate_id),
            None,
        )
        if candidate is None or candidate_content_hash(candidate) != plan.candidate_hash:
            raise ReplayGuardError("CONFIRMED_PLAN_NOT_FRESH", "ConfirmedPlan 绑定的候选内容已变化。")
        try:
            binding, snapshot, planning_assets = self._confirmation_binding(task, planning, candidate)
        except (
            PlanConfirmationGuardError,
            ParameterPlanningAssetError,
            CaseRetrievalAssetError,
            CaseRetrievalGuardError,
            ConfirmationStateChangedError,
        ) as error:
            raise ReplayGuardError(
                "CONFIRMED_PLAN_NOT_FRESH",
                "ConfirmedPlan 的当前版本、快照或资产绑定已失效。",
                failed_validation=getattr(error, "code", type(error).__name__),
            ) from error
        freshness = ConfirmedPlanFreshnessEvaluator().evaluate(plan, binding)
        if not freshness.replay_eligible:
            raise ReplayGuardError(
                "CONFIRMED_PLAN_NOT_FRESH",
                "ConfirmedPlan freshness check 未通过。",
                failed_validation=",".join(freshness.stale_reason_codes),
            )
        safety = ParameterSafetyValidator(planning_assets.safety_policy).validate(
            candidate,
            snapshot=snapshot,
            versions=SafetyVersionContext(
                constraint_snapshot_version=binding.parameter_constraint_snapshot_version,
                rule_set_version=binding.rule_set_version,
                direction_rule_version=binding.direction_rule_version,
                safety_rule_version=binding.safety_rule_version,
                diagnostic_result_version=binding.diagnostic_result_version,
                case_retrieval_result_version=binding.case_retrieval_result_version,
            ),
        )
        if safety.validation_status != "PASSED":
            raise ReplayGuardError(
                "CONFIRMED_PLAN_SAFETY_INVALID",
                "ConfirmedPlan 未通过回放前安全复核。",
            )
        return plan

    def _load_replay_inputs(
        self,
        task: Task,
    ) -> tuple[StoredReplayInput, ReplayEvaluationRuleSnapshot, str, int]:
        source = self._store.get_replay_input(task.task_id)
        if (
            source.manifest is None
            or source.batch is None
            or source.replay_evaluation_rules is None
            or task.data_import is None
        ):
            raise ReplayGuardError("REPLAY_INPUT_MISSING", "回放输入或评价快照缺失。")
        if self._demo_asset_root is None or self._expected_dataset_manifest_hash is None:
            raise ReplayGuardError("DATASET_ASSET_MISSING", "回放所需 DatasetManifest 未装配。")
        manifest_path = self._demo_asset_root / "dataset-manifest.json"
        rules_path = self._demo_asset_root / "import-rules.json"
        try:
            manifest_bytes = manifest_path.read_bytes()
            trusted_manifest = json.loads(manifest_bytes)
            rules_bytes = rules_path.read_bytes()
            trusted_rules = json.loads(rules_bytes)
        except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ReplayGuardError(
                "DATASET_ASSET_MISSING",
                "回放所需受信任数据资产缺失或无效。",
            ) from error
        if hashlib.sha256(manifest_bytes).hexdigest() != self._expected_dataset_manifest_hash:
            raise ReplayGuardError(
                "DATASET_ASSET_HASH_MISMATCH",
                "DatasetManifest 内容哈希不匹配。",
            )
        hashes = task.data_import.hashes
        if (
            trusted_manifest.get("rules_file_hash") != hashlib.sha256(rules_bytes).hexdigest()
            or trusted_manifest.get("scenario_ref_hash") != hashes.scenario_ref_hash
            or source.manifest.get("scenario_ref_hash") != hashes.scenario_ref_hash
            or source.manifest.get("canonical_observation_hash") != hashes.canonical_observation_hash
            or trusted_rules.get("replay_evaluation_rules") != source.replay_evaluation_rules
        ):
            raise ReplayGuardError(
                "REPLAY_INPUT_HASH_MISMATCH",
                "回放输入、场景或评价快照绑定不匹配。",
            )
        try:
            evaluation_rules = ReplayEvaluationRuleSnapshot(**source.replay_evaluation_rules)
        except (TypeError, ValueError) as error:
            raise ReplayGuardError(
                "REPLAY_EVALUATION_SNAPSHOT_INVALID",
                "回放评价快照格式无效。",
            ) from error
        if evaluation_rules.evaluation_rule_version != task.versions.evaluation_rule_version:
            raise ReplayGuardError(
                "REPLAY_EVALUATION_SNAPSHOT_INVALID",
                "回放评价规则版本不匹配。",
            )
        scenario_ref = trusted_manifest.get("scenario_ref")
        seed = trusted_manifest.get("random_seed")
        if not isinstance(scenario_ref, str):
            raise ReplayGuardError("SCENARIO_REFERENCE_INVALID", "场景引用无法解析。")
        if not isinstance(seed, int) or isinstance(seed, bool):
            raise ReplayGuardError(
                "SIMULATOR_INPUT_MISMATCH",
                "导入数据固定 seed 绑定无效。",
            )
        return source, evaluation_rules, scenario_ref, seed

    def _persist_replay_success(
        self,
        *,
        task: Task,
        plan: ConfirmedPlan,
        source: StoredReplayInput,
        computation: ReplayComputation,
        evaluation_rules: ReplayEvaluationRuleSnapshot,
        request_idempotency_key: str,
    ) -> tuple[Task, ReplayResult]:
        if task.data_import is None or source.replay_evaluation_rules is None:
            raise ReplayGuardError("REPLAY_INPUT_MISSING", "回放输入或评价快照缺失。")
        replay_input_hashes = {
            **computation.input_asset_hashes,
            "dataset_manifest": self._expected_dataset_manifest_hash or "",
            "dataset_raw": task.data_import.hashes.raw_file_hash,
            "replay_evaluation_rule_snapshot": canonical_hash(
                source.replay_evaluation_rules
            ),
            **{
                f"confirmed_plan_source:{name}": value
                for name, value in plan.source_asset_hashes.items()
            },
        }
        computation = replace(computation, input_asset_hashes=replay_input_hashes)
        now = self._clock.now()
        result = create_replay_result(
            task_id=task.task_id,
            confirmed_plan_id=plan.confirmed_plan_id,
            confirmed_plan_hash=plan.confirmed_plan_hash,
            candidate_id=plan.candidate_id,
            candidate_hash=plan.candidate_hash,
            request_idempotency_key=request_idempotency_key,
            attempt_count=1,
            dataset_version=task.versions.dataset_version,
            schema_version=task.versions.schema_version,
            generator_version=task.versions.generator_version,
            rule_set_version=task.versions.rule_set_version,
            model_version=task.versions.model_version,
            computation=computation,
            evaluation_rule_version=evaluation_rules.evaluation_rule_version,
            created_at=now,
            completed_at=now,
        )
        replaying_task = replace(
            task,
            status=TaskStatus.REPLAYING,
            stages=workflow_for(TaskStatus.REPLAYING),
        )
        completed_task = replace(
            replaying_task,
            status=TaskStatus.REPLAYED,
            stages=workflow_for(TaskStatus.REPLAYED),
            replay_result=result,
        )
        base_event = create_audit_event(
            task_id=task.task_id,
            actor_id=task.actor.actor_id,
            actor_role=task.actor.actor_role,
            display_name=task.actor.display_name,
            occurred_at=now,
            result="SUCCESS",
            rule_set_version=task.versions.rule_set_version,
            candidate_id=plan.candidate_id,
            candidate_hash=plan.candidate_hash,
            plan=plan,
        )
        event = replace(
            base_event,
            action="RUN_PAIRED_REPLAY",
            replay_result_id=result.replay_result_id,
            replay_result_hash=result.result_hash,
            simulator_version=result.simulator_version,
            evaluation_rule_version=result.replay_evaluation_rule_version,
            baseline_reproduction_status=result.baseline_reproduction_status,
            replay_status=result.replay_status,
            attempt_count=result.attempt_count,
        )
        try:
            return self._store.save_replay_success(
                replaying_task,
                completed_task,
                result,
                event,
                computation.hidden_binding_hash,
            )
        except ReplayResultConflictError as error:
            raise ReplayGuardError(
                "REPLAY_RESULT_CONFLICT",
                "当前任务回放结果已发生冲突。",
            ) from error

    def run_replay(
        self,
        task_id: str,
        confirmed_plan_id: str,
        confirmed_plan_hash: str,
        request_idempotency_key: str,
    ) -> tuple[Task, ReplayResult]:
        try:
            task = self.get_task(task_id)
        except PlanConfirmationGuardError as error:
            if self._store.get_current_confirmed_plan(task_id) is None:
                raise ReplayGuardError(
                    "CONFIRMED_PLAN_NOT_FOUND",
                    "当前任务缺少 ConfirmedPlan。",
                ) from error
            raise ReplayGuardError(error.code, error.message) from error
        if task is None:
            raise ReplayGuardError("TASK_NOT_FOUND", "调机任务不存在。", 404)
        if self._store.get_current_replay_result(task_id) is not None:
            raise ReplayGuardError("REPLAY_RESULT_CONFLICT", "当前任务已存在有效 ReplayResult。")
        if task.status is not TaskStatus.PLAN_CONFIRMED:
            raise ReplayGuardError(
                "TASK_NOT_PLAN_CONFIRMED",
                "只有 PLAN_CONFIRMED 任务可以运行离线模拟回放。",
            )
        plan = self._validate_replay_plan(
            task,
            confirmed_plan_id,
            confirmed_plan_hash,
        )
        if self._replay_orchestrator is None:
            raise ReplayGuardError("SIMULATOR_ASSET_MISSING", "本地模拟器资产未装配。")
        source, evaluation_rules, scenario_ref, seed = self._load_replay_inputs(task)
        computation = self._replay_orchestrator.execute_pair(
            scenario_ref=scenario_ref,
            scenario_ref_hash=task.data_import.hashes.scenario_ref_hash,
            sample_count=task.data_import.sample_count,
            seed=seed,
            current_values=plan.current_values,
            proposed_values=plan.proposed_values,
            imported_baseline_canonical_hash=task.data_import.hashes.canonical_observation_hash,
            evaluation_rules=evaluation_rules,
            control_limits=ControlLimitRegistry.snapshot_for(
                task.versions.rule_set_version
            ),
        )
        return self._persist_replay_success(
            task=task,
            plan=plan,
            source=source,
            computation=computation,
            evaluation_rules=evaluation_rules,
            request_idempotency_key=request_idempotency_key,
        )

    def qualify_device_execution(
        self,
        task_id: str,
        confirmed_plan_id: str,
        confirmed_plan_hash: str,
    ) -> DeviceExecutionQualification:
        try:
            task = self.get_task(task_id)
        except (PlanConfirmationGuardError, ReplayGuardError) as error:
            raise DeviceQualificationError(
                getattr(error, "code", "CONFIRMED_PLAN_INVALID"),
                getattr(error, "message", "ConfirmedPlan 完整性校验失败。"),
            ) from error
        if task is None:
            raise DeviceQualificationError("TASK_NOT_FOUND", "调机任务不存在。")
        try:
            plan = self._validate_replay_plan(
                task,
                confirmed_plan_id,
                confirmed_plan_hash,
            )
        except ReplayGuardError as error:
            mapped_code = (
                "SAFETY_REVALIDATION_FAILED"
                if error.code == "CONFIRMED_PLAN_SAFETY_INVALID"
                else error.code
            )
            raise DeviceQualificationError(mapped_code, error.message) from error
        try:
            replay_result = self._store.get_current_replay_result(task_id)
        except ReplayGuardError as error:
            raise DeviceQualificationError(error.code, error.message) from error
        if replay_result is None or task.replay_result is None:
            raise DeviceQualificationError(
                "REPLAY_RESULT_NOT_FOUND",
                "当前 ConfirmedPlan 缺少 ReplayResult。",
            )
        if task.status is not TaskStatus.REPLAYED:
            raise DeviceQualificationError(
                "TASK_NOT_REPLAYED",
                "只有已完成确定性离线回放的任务可以执行 OPC-UA sandbox 下发。",
                replay_result_id=replay_result.replay_result_id,
                replay_result_hash=replay_result.result_hash,
            )
        if (
            replay_result.task_id != task_id
            or replay_result.confirmed_plan_id != plan.confirmed_plan_id
            or replay_result.confirmed_plan_hash != plan.confirmed_plan_hash
            or replay_result.candidate_id != plan.candidate_id
            or replay_result.candidate_hash != plan.candidate_hash
        ):
            raise DeviceQualificationError(
                "REPLAY_PLAN_BINDING_MISMATCH",
                "ReplayResult 未绑定当前 ConfirmedPlan。",
                replay_result_id=replay_result.replay_result_id,
                replay_result_hash=replay_result.result_hash,
            )
        if replay_result.baseline_reproduction_status != "PASSED":
            raise DeviceQualificationError(
                "BASELINE_REPRODUCTION_FAILED",
                "ReplayResult baseline reproduction 未通过。",
                replay_result_id=replay_result.replay_result_id,
                replay_result_hash=replay_result.result_hash,
            )
        planning = self._store.get_current_parameter_planning(task_id)
        if planning is None:
            raise DeviceQualificationError(
                "CONFIRMED_PLAN_NOT_FRESH",
                "当前参数规划结果已缺失。",
                replay_result_id=replay_result.replay_result_id,
                replay_result_hash=replay_result.result_hash,
            )
        candidate = next(
            (
                item
                for item in planning.ordered_candidates
                if item.candidate_id == plan.candidate_id
            ),
            None,
        )
        if candidate is None or candidate_content_hash(candidate) != plan.candidate_hash:
            raise DeviceQualificationError(
                "CONFIRMED_PLAN_NOT_FRESH",
                "ConfirmedPlan 绑定的候选内容已变化。",
                replay_result_id=replay_result.replay_result_id,
                replay_result_hash=replay_result.result_hash,
            )
        try:
            binding, snapshot, planning_assets = self._confirmation_binding(
                task,
                planning,
                candidate,
            )
        except (
            PlanConfirmationGuardError,
            ParameterPlanningAssetError,
            CaseRetrievalAssetError,
            CaseRetrievalGuardError,
            ConfirmationStateChangedError,
        ) as error:
            raise DeviceQualificationError(
                "CONFIRMED_PLAN_NOT_FRESH",
                "ConfirmedPlan 的当前版本、快照或资产绑定已失效。",
                replay_result_id=replay_result.replay_result_id,
                replay_result_hash=replay_result.result_hash,
            ) from error
        freshness = ConfirmedPlanFreshnessEvaluator().evaluate(plan, binding)
        if not freshness.replay_eligible:
            raise DeviceQualificationError(
                "CONFIRMED_PLAN_NOT_FRESH",
                "ConfirmedPlan freshness check 未通过。",
                replay_result_id=replay_result.replay_result_id,
                replay_result_hash=replay_result.result_hash,
            )
        safety = ParameterSafetyValidator(planning_assets.safety_policy).validate(
            candidate,
            snapshot=snapshot,
            versions=SafetyVersionContext(
                constraint_snapshot_version=binding.parameter_constraint_snapshot_version,
                rule_set_version=binding.rule_set_version,
                direction_rule_version=binding.direction_rule_version,
                safety_rule_version=binding.safety_rule_version,
                diagnostic_result_version=binding.diagnostic_result_version,
                case_retrieval_result_version=binding.case_retrieval_result_version,
            ),
        )
        changed_parameters = tuple(
            name
            for name in sorted(plan.current_values)
            if plan.current_values[name] != plan.proposed_values.get(name)
        )
        return DeviceExecutionQualification(
            task_id=task_id,
            confirmed_plan_id=plan.confirmed_plan_id,
            confirmed_plan_hash=plan.confirmed_plan_hash,
            replay_result_id=replay_result.replay_result_id,
            replay_result_hash=replay_result.result_hash,
            replay_status=replay_result.replay_status,
            baseline_reproduction_status=replay_result.baseline_reproduction_status,
            parameter_family=plan.parameter_family,
            current_values=plan.current_values,
            proposed_values=plan.proposed_values,
            delta_ticks={
                name: int(plan.delta_ticks[name])
                for name in changed_parameters
                if name in plan.delta_ticks
            },
            changed_parameters=changed_parameters,
            safety_validator_version=safety.safety_rule_version,
            safety_validation_result=safety.validation_status,
            actor_id=task.actor.actor_id,
            actor_role=task.actor.actor_role,
            display_name=task.actor.display_name,
            confirmed_at=plan.confirmed_at,
        )

    def has_task(self, task_id: str) -> bool:
        return self._store.has_task(task_id)

    def _confirmation_binding(
        self,
        task: Task,
        planning: ParameterPlanningResultRecord,
        candidate,
    ) -> tuple[FreshnessBinding, ParameterConstraintSnapshot, object]:
        if (
            self._planning_asset_root is None
            or self._expected_planning_manifest_hash is None
            or task.data_import is None
            or task.anomaly_detection is None
            or task.diagnostic_result is None
        ):
            self._raise_confirmation_guard(
                task,
                candidate.candidate_id,
                candidate.candidate_hash,
                "PLANNING_RESULT_STALE",
                "确认所需的任务、诊断或规划输入不完整。",
            )
        planning_assets = ParameterPlanningAssetLoader(
            self._planning_asset_root,
            self._expected_planning_manifest_hash,
        ).load()
        if (
            planning.planning_asset_manifest_hash != planning_assets.manifest_hash
            or planning.rule_set_version != task.versions.rule_set_version
            or planning.direction_rule_version
            != planning_assets.direction_rules.direction_rule_version
            or planning.safety_rule_version
            != planning_assets.safety_policy.safety_rule_version
            or planning.planning_rule_version
            != planning_assets.planning_policy.planning_rule_version
        ):
            raise PlanConfirmationGuardError(
                "RULE_VERSION_CHANGED",
                "当前 ParameterPlanningResult 绑定的规则资产已变化。",
            )
        if (
            self._diagnostic_asset_root is None
            or self._expected_diagnostic_manifest_hash is None
        ):
            raise PlanConfirmationGuardError(
                "DIAGNOSTIC_ASSETS_MISSING",
                "确认所需的固定诊断资产未装配。",
            )
        try:
            diagnostic_assets = DiagnosticAssetLoader(
                self._diagnostic_asset_root,
                self._expected_diagnostic_manifest_hash,
            ).load()
        except DiagnosticAssetError as error:
            raise PlanConfirmationGuardError(
                "DIAGNOSTIC_ASSET_HASH_MISMATCH",
                "当前诊断资产内容或版本已变化。",
            ) from error
        if (
            diagnostic_assets.input_asset_hashes
            != task.diagnostic_result.input_asset_hashes
            or diagnostic_assets.model.get("model_version")
            != task.diagnostic_result.model_version
            or diagnostic_assets.preprocessing.get("preprocessing_version")
            != task.diagnostic_result.preprocessing_version
            or diagnostic_assets.feature_definition.get("feature_definition_version")
            != task.diagnostic_result.feature_definition_version
        ):
            raise PlanConfirmationGuardError(
                "DIAGNOSTIC_ASSET_HASH_MISMATCH",
                "当前诊断资产与 DiagnosticResult 绑定不一致。",
            )
        source = self._store.get_confirmation_input(task.task_id)
        if source.parameter_constraints is None or source.control_limits is None:
            self._raise_confirmation_guard(
                task,
                candidate.candidate_id,
                candidate.candidate_hash,
                "SNAPSHOT_VERSION_MISMATCH",
                "确认所需只读快照缺失。",
            )
        try:
            snapshot = ParameterConstraintSnapshot.from_payload(
                source.parameter_constraints
            )
        except (KeyError, TypeError, ValueError) as error:
            raise PlanConfirmationGuardError(
                "PARAMETER_CONSTRAINT_SNAPSHOT_CHANGED",
                "当前 ParameterConstraintSnapshot 格式无效。",
            ) from error
        parameter_snapshot_file_hash = hashlib.sha256(
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
            parameter_snapshot_file_hash
            != planning_assets.expected_parameter_constraint_snapshot_hash
            or snapshot.snapshot_version != planning.constraint_snapshot_version
            or snapshot.rule_set_version != planning.rule_set_version
        ):
            raise PlanConfirmationGuardError(
                "PARAMETER_CONSTRAINT_SNAPSHOT_CHANGED",
                "当前 ParameterConstraintSnapshot 内容或版本已变化。",
            )
        current_detection = self._store.get_current_detection(task.task_id)
        current_diagnostic = self._store.get_current_diagnostic(task.task_id)
        if (
            current_detection is None
            or current_detection.detection_result_id
            != task.anomaly_detection.detection_result_id
        ):
            raise PlanConfirmationGuardError(
                "DETECTION_VERSION_CHANGED",
                "当前异常检测结果版本已变化。",
            )
        if (
            current_diagnostic is None
            or current_diagnostic.diagnostic_result_id
            != task.diagnostic_result.diagnostic_result_id
        ):
            raise PlanConfirmationGuardError(
                "DIAGNOSTIC_VERSION_CHANGED",
                "当前诊断结果版本已变化。",
            )
        if (
            task.diagnostic_result.evidence_status != "SUFFICIENT_EVIDENCE"
            or task.diagnostic_result.diagnostic_result_id
            != planning.diagnostic_result_id
            or task.diagnostic_result.diagnostic_result_version
            != planning.diagnostic_result_version
        ):
            raise PlanConfirmationGuardError(
                "DIAGNOSTIC_VERSION_CHANGED",
                "当前诊断证据或版本不再允许确认参数候选。",
            )
        expected_control = ControlLimitRegistry.snapshot_for(
            task.versions.rule_set_version
        )
        expected_control_payload = {
            "snapshot_version": expected_control.snapshot_version,
            "rule_set_version": expected_control.rule_set_version,
            "center_lower_limit": f"{expected_control.center_lower_limit:.6f}",
            "corner_lower_limit": f"{expected_control.corner_lower_limit:.6f}",
            "asymmetry_limit": f"{expected_control.asymmetry_limit:.6f}",
            "corner_std_limit": f"{expected_control.corner_std_limit:.6f}",
        }
        if source.control_limits != expected_control_payload:
            raise PlanConfirmationGuardError(
                "CONTROL_LIMIT_SNAPSHOT_CHANGED",
                "当前控制限快照内容与冻结版本不一致。",
            )
        measurement_hash = canonical_measurement_hash(source.measurements)
        try:
            features = FeatureEngineer().derive(source.measurements)
        except FeatureEngineeringError as error:
            raise PlanConfirmationGuardError(
                "INPUT_DATA_CHANGED",
                "当前 Measurement 无法生成有效 DerivedFeatureSet。",
            ) from error
        if (
            measurement_hash != task.data_import.hashes.canonical_observation_hash
            or features.input_feature_hash
            != task.diagnostic_result.input_feature_hash
        ):
            raise PlanConfirmationGuardError(
                "INPUT_DATA_CHANGED",
                "当前 Measurement 或 DerivedFeatureSet 已变化。",
            )
        current_parameter_values: dict[str, object] = {}
        for name in PARAMETER_FIELDS:
            try:
                values = sorted(
                    {
                        f"{Decimal(row[name]):.6f}"
                        for row in source.measurements
                        if name in row
                    }
                )
            except (InvalidOperation, TypeError, ValueError) as error:
                raise PlanConfirmationGuardError(
                    "CURRENT_PARAMETER_MISMATCH",
                    "当前参数值格式无效。",
                ) from error
            if len(values) != 1:
                raise PlanConfirmationGuardError(
                    "CURRENT_PARAMETER_MISMATCH",
                    "当前参数值不一致，候选不可确认。",
                )
            current_parameter_values[name] = values[0]
        if candidate.current_values != current_parameter_values:
            raise PlanConfirmationGuardError(
                "CURRENT_PARAMETER_MISMATCH",
                "候选 current_values 与服务端当前参数值不一致。",
            )
        current_parameter_hash = canonical_hash(current_parameter_values)
        source_hashes = {
            "detection_result": task.anomaly_detection.result_hash,
            "diagnostic_result": task.diagnostic_result.result_hash,
            "planning_result": planning.result_hash,
            "planning_asset_manifest": planning_assets.manifest_hash,
        }
        source_hashes.update(
            {
                f"diagnostic_asset:{key}": value
                for key, value in diagnostic_assets.input_asset_hashes.items()
            }
        )
        if self._demo_asset_root is None or self._expected_dataset_manifest_hash is None:
            raise PlanConfirmationGuardError(
                "DATASET_ASSETS_MISSING",
                "确认所需的固定数据资产未装配。",
            )
        dataset_raw_path = self._demo_asset_root / "aa-demo-batch.csv"
        try:
            dataset_raw_hash = hashlib.sha256(dataset_raw_path.read_bytes()).hexdigest()
        except FileNotFoundError as error:
            raise PlanConfirmationGuardError(
                "DATASET_ASSET_HASH_MISMATCH",
                "固定观测文件已缺失。",
            ) from error
        if dataset_raw_hash != task.data_import.hashes.raw_file_hash:
            raise PlanConfirmationGuardError(
                "DATASET_ASSET_HASH_MISMATCH",
                "固定观测文件内容已变化。",
            )
        source_hashes["dataset_manifest"] = self._expected_dataset_manifest_hash
        source_hashes["dataset_raw"] = dataset_raw_hash
        if source.manifest is None or source.batch is None:
            raise PlanConfirmationGuardError(
                "DATASET_ASSET_HASH_MISMATCH",
                "已保存的数据 Manifest 或 Batch 绑定已缺失。",
            )
        if (
            source.manifest.get("dataset_manifest_hash")
            != self._expected_dataset_manifest_hash
            or source.manifest.get("raw_file_hash")
            != task.data_import.hashes.raw_file_hash
            or source.manifest.get("canonical_observation_hash")
            != task.data_import.hashes.canonical_observation_hash
            or source.manifest.get("scenario_ref_hash")
            != task.data_import.hashes.scenario_ref_hash
            or source.manifest.get("versions", {}).get("dataset_version")
            != task.versions.dataset_version
        ):
            raise PlanConfirmationGuardError(
                "DATASET_ASSET_HASH_MISMATCH",
                "持久化 DatasetManifest 脱敏投影与任务输入绑定不一致。",
            )
        source_hashes["stored_dataset_manifest"] = canonical_hash(source.manifest)
        source_hashes["stored_batch"] = canonical_hash(source.batch)
        retrieval = self._store.get_current_case_retrieval_binding(task.task_id)
        approved_case_index_version = None
        if retrieval is None and planning.case_retrieval_result_id is not None:
            raise PlanConfirmationGuardError(
                "RETRIEVAL_VERSION_CHANGED",
                "当前 CaseRetrievalResult 已缺失。",
            )
        if retrieval is not None:
            if self._case_asset_root is None or self._expected_case_manifest_hash is None:
                self._raise_confirmation_guard(
                    task,
                    candidate.candidate_id,
                    candidate.candidate_hash,
                    "SUPPORTING_CASE_CHANGED",
                    "候选引用的受信任案例资产未装配。",
                )
            case_manifest, case_asset_hashes = self._confirmation_case_asset_binding()
            approved_case_index_version = case_manifest["case_index_version"]
            source_hashes["case_asset_manifest"] = case_asset_hashes["manifest.json"]
            source_hashes["case_retrieval_result"] = retrieval.result_hash
            source_hashes["case_collection"] = case_asset_hashes[
                "approved-cases.json"
            ]
            source_hashes["case_index"] = case_asset_hashes["index.json"]
            if (
                retrieval.retrieval_result_id != planning.case_retrieval_result_id
                or retrieval.diagnostic_result_id != planning.diagnostic_result_id
                or retrieval.retrieval_result_version
                != CASE_RETRIEVAL_RESULT_VERSION
                or planning.case_retrieval_result_version
                != retrieval.retrieval_result_version
                or retrieval.retrieval_rule_version != RETRIEVAL_RULE_VERSION
                or retrieval.case_index_version != approved_case_index_version
                or retrieval.case_index_hash != case_asset_hashes["index.json"]
                or retrieval.feature_definition_version
                != planning.feature_definition_version
            ):
                raise PlanConfirmationGuardError(
                    "RETRIEVAL_VERSION_CHANGED",
                    "当前 CaseRetrievalResult 或案例索引版本已变化。",
                )
            for case_id in candidate.supporting_case_ids:
                case_hash = retrieval.case_content_hashes.get(case_id)
                if case_hash is None:
                    self._raise_confirmation_guard(
                        task,
                        candidate.candidate_id,
                        candidate.candidate_hash,
                        "SUPPORTING_CASE_CHANGED",
                        "候选引用的 supporting case 已缺失。",
                    )
                source_hashes[f"supporting_case:{case_id}"] = case_hash
        case_index_hash = None if retrieval is None else retrieval.case_index_hash
        case_asset_manifest_hash = (
            None
            if retrieval is None
            else source_hashes["case_asset_manifest"]
        )
        input_bindings = {
            "task_id": task.task_id,
            "diagnostic_result_id": current_diagnostic.diagnostic_result_id,
            "diagnostic_result_hash": current_diagnostic.result_hash,
            "case_retrieval_result_id": (
                None if retrieval is None else retrieval.retrieval_result_id
            ),
            "case_retrieval_result_hash": (
                None if retrieval is None else retrieval.result_hash
            ),
            "measurement_hash": measurement_hash,
            "feature_hash": features.input_feature_hash,
            "parameter_constraint_snapshot_hash": parameter_snapshot_file_hash,
            "planning_asset_manifest_hash": planning_assets.manifest_hash,
            "case_index_hash": case_index_hash,
            "case_asset_manifest_hash": case_asset_manifest_hash,
            "historical_case_ids": (
                () if retrieval is None else retrieval.ordered_case_ids
            ),
        }
        if planning.input_hash != parameter_planning_input_hash(input_bindings):
            raise PlanConfirmationGuardError(
                "PLANNING_RESULT_STALE",
                "当前诊断、案例检索、Measurement 或资产绑定与规划输入不一致。",
            )
        binding = FreshnessBinding(
            input_data_version=task.versions.dataset_version,
            input_measurement_hash=measurement_hash,
            current_parameter_hash=current_parameter_hash,
            detection_result_id=task.anomaly_detection.detection_result_id,
            detection_result_version=DETECTION_RESULT_VERSION,
            diagnostic_result_id=task.diagnostic_result.diagnostic_result_id,
            diagnostic_result_version=task.diagnostic_result.diagnostic_result_version,
            case_retrieval_result_id=(
                None if retrieval is None else retrieval.retrieval_result_id
            ),
            case_retrieval_result_version=(
                None if retrieval is None else CASE_RETRIEVAL_RESULT_VERSION
            ),
            planning_result_id=planning.planning_result_id,
            planning_result_version=planning.planning_result_version,
            candidate_hash=candidate.candidate_hash,
            control_limit_snapshot_version=source.control_limits["snapshot_version"],
            control_limit_snapshot_hash=canonical_hash(source.control_limits),
            parameter_constraint_snapshot_version=snapshot.snapshot_version,
            parameter_constraint_snapshot_hash=canonical_hash(
                source.parameter_constraints
            ),
            direction_rule_version=planning.direction_rule_version,
            safety_rule_version=planning.safety_rule_version,
            planning_rule_version=planning.planning_rule_version,
            rule_set_version=planning.rule_set_version,
            feature_definition_version=planning.feature_definition_version,
            model_version=task.diagnostic_result.model_version,
            preprocessing_version=task.diagnostic_result.preprocessing_version,
            approved_case_index_version=approved_case_index_version,
            source_asset_hashes=dict(sorted(source_hashes.items())),
        )
        return binding, snapshot, planning_assets

    def _confirmation_file_asset_token(self, *, include_case_assets: bool) -> str:
        if (
            self._planning_asset_root is None
            or self._expected_planning_manifest_hash is None
            or self._diagnostic_asset_root is None
            or self._expected_diagnostic_manifest_hash is None
            or self._demo_asset_root is None
            or self._expected_dataset_manifest_hash is None
        ):
            raise PlanConfirmationGuardError(
                "ASSET_HASH_MISMATCH",
                "确认所需的受信任文件资产未完整装配。",
            )
        planning_assets = ParameterPlanningAssetLoader(
            self._planning_asset_root,
            self._expected_planning_manifest_hash,
        ).load()
        diagnostic_assets = DiagnosticAssetLoader(
            self._diagnostic_asset_root,
            self._expected_diagnostic_manifest_hash,
        ).load()
        dataset_raw_hash = hashlib.sha256(
            (self._demo_asset_root / "aa-demo-batch.csv").read_bytes()
        ).hexdigest()
        public_assets = self._asset_loader.load()
        payload: dict[str, object] = {
            "public_actor": asdict(public_assets.actor),
            "public_versions": asdict(public_assets.versions),
            "planning_manifest": planning_assets.manifest_hash,
            "diagnostic_assets": diagnostic_assets.input_asset_hashes,
            "dataset_manifest": self._expected_dataset_manifest_hash,
            "dataset_raw": dataset_raw_hash,
        }
        if include_case_assets:
            case_manifest, case_hashes = self._confirmation_case_asset_binding()
            payload["case_manifest"] = case_manifest["case_index_version"]
            payload["case_assets"] = case_hashes
        return canonical_hash(payload)

    def _confirmation_case_asset_binding(
        self,
    ) -> tuple[dict[str, object], dict[str, str]]:
        if self._case_asset_root is None or self._expected_case_manifest_hash is None:
            raise CaseRetrievalAssetError(
                "CASE_ASSETS_MISSING",
                "候选引用的受信任案例资产未装配。",
            )
        try:
            manifest_bytes = (self._case_asset_root / "manifest.json").read_bytes()
            manifest = json.loads(manifest_bytes)
        except FileNotFoundError as error:
            raise CaseRetrievalAssetError(
                "CASE_MANIFEST_MISSING",
                "案例资产 Manifest 已缺失。",
            ) from error
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise CaseRetrievalAssetError(
                "CASE_MANIFEST_INVALID",
                "案例资产 Manifest 格式无效。",
            ) from error
        manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
        files = manifest.get("files") if isinstance(manifest, dict) else None
        if (
            manifest_hash != self._expected_case_manifest_hash
            or not isinstance(files, dict)
            or manifest.get("case_index_version") != CASE_INDEX_VERSION
            or manifest.get("case_schema_version") != CASE_SCHEMA_VERSION
            or manifest.get("scaler_version") != SCALER_VERSION
            or manifest.get("compatibility_rule_version")
            != COMPATIBILITY_RULE_VERSION
            or manifest.get("retrieval_rule_version") != RETRIEVAL_RULE_VERSION
            or manifest.get("feature_definition_version")
            != FEATURE_DEFINITION_VERSION
        ):
            raise CaseRetrievalAssetError(
                "CASE_MANIFEST_HASH_MISMATCH",
                "案例资产 Manifest 内容、版本或哈希不匹配。",
            )
        hashes = {"manifest.json": manifest_hash}
        for name in ApprovedCaseAssetLoader.REQUIRED_FILES:
            try:
                content = (self._case_asset_root / name).read_bytes()
            except FileNotFoundError as error:
                raise CaseRetrievalAssetError(
                    "CASE_ASSET_MISSING",
                    f"案例资产已缺失：{name}",
                ) from error
            actual_hash = hashlib.sha256(content).hexdigest()
            if files.get(name) != actual_hash:
                raise CaseRetrievalAssetError(
                    "CASE_ASSET_HASH_MISMATCH",
                    f"案例资产内容哈希不匹配：{name}",
                )
            hashes[name] = actual_hash
        if manifest.get("case_collection_hash") != hashes["approved-cases.json"]:
            raise CaseRetrievalAssetError(
                "CASE_ASSET_HASH_MISMATCH",
                "案例集合内容哈希与 Manifest 不一致。",
            )
        return manifest, hashes

    def _refresh_confirmed_plan(self, task: Task) -> Task:
        plan = task.confirmed_plan
        if plan is None or plan.status == "STALE":
            return task
        reasons: tuple[str, ...] = ()
        try:
            current_detection = self._store.get_current_detection(task.task_id)
            current_diagnostic = self._store.get_current_diagnostic(task.task_id)
            planning = self._store.get_current_parameter_planning(task.task_id)
        except DetectionGuardError:
            reasons = ("ASSET_HASH_MISMATCH",)
            current_detection = None
            current_diagnostic = None
            planning = None
        except DiagnosticGuardError:
            reasons = ("DIAGNOSTIC_VERSION_CHANGED",)
            current_detection = None
            current_diagnostic = None
            planning = None
        except ParameterPlanningGuardError:
            reasons = ("PLANNING_VERSION_CHANGED",)
            current_detection = None
            current_diagnostic = None
            planning = None
        if reasons:
            pass
        elif (
            current_detection is None
            or current_detection.detection_result_id != plan.detection_result_id
        ):
            reasons = ("DETECTION_VERSION_CHANGED",)
        elif (
            current_diagnostic is None
            or current_diagnostic.diagnostic_result_id != plan.diagnostic_result_id
        ):
            reasons = ("DIAGNOSTIC_VERSION_CHANGED",)
        elif planning is None:
            reasons = ("PLANNING_VERSION_CHANGED",)
        else:
            candidate = next(
                (
                    item
                    for item in planning.ordered_candidates
                    if item.candidate_id == plan.candidate_id
                ),
                None,
            )
            if candidate is None:
                reasons = ("CANDIDATE_HASH_CHANGED",)
            else:
                try:
                    binding, _snapshot, _assets = self._confirmation_binding(
                        task, planning, candidate
                    )
                    evaluation = ConfirmedPlanFreshnessEvaluator().evaluate(
                        plan, binding
                    )
                    reasons = evaluation.stale_reason_codes
                except ParameterPlanningAssetError:
                    reasons = ("RULE_VERSION_CHANGED",)
                except CaseRetrievalAssetError:
                    reasons = ("SUPPORTING_CASE_CHANGED",)
                except CaseRetrievalGuardError:
                    reasons = ("RETRIEVAL_VERSION_CHANGED",)
                except ConfirmationStateChangedError:
                    reasons = ("ASSET_HASH_MISMATCH",)
                except ParameterPlanningGuardError:
                    reasons = ("ASSET_HASH_MISMATCH",)
                except PlanConfirmationGuardError as error:
                    reasons = {
                        "CONTROL_LIMIT_SNAPSHOT_CHANGED": (
                            "CONTROL_LIMIT_SNAPSHOT_CHANGED",
                        ),
                        "DETECTION_VERSION_CHANGED": (
                            "DETECTION_VERSION_CHANGED",
                        ),
                        "DIAGNOSTIC_VERSION_CHANGED": (
                            "DIAGNOSTIC_VERSION_CHANGED",
                        ),
                        "INPUT_DATA_CHANGED": ("INPUT_DATA_CHANGED",),
                        "CURRENT_PARAMETER_MISMATCH": (
                            "CURRENT_PARAMETER_CHANGED",
                        ),
                        "PARAMETER_CONSTRAINT_SNAPSHOT_CHANGED": (
                            "PARAMETER_CONSTRAINT_SNAPSHOT_CHANGED",
                        ),
                        "RETRIEVAL_VERSION_CHANGED": (
                            "RETRIEVAL_VERSION_CHANGED",
                        ),
                        "RULE_VERSION_CHANGED": ("RULE_VERSION_CHANGED",),
                    }.get(error.code, ("ASSET_HASH_MISMATCH",))
                except (KeyError, TypeError, ValueError, InvalidOperation):
                    reasons = ("ASSET_HASH_MISMATCH",)
        if not reasons:
            return task
        stale_plan = replace(
            plan,
            status="STALE",
            stale_reason_codes=tuple(dict.fromkeys(reasons)),
        )
        stale_task = replace(task, confirmed_plan=stale_plan)
        return self._store.mark_confirmed_plan_stale(stale_task, stale_plan)

    def _raise_confirmation_guard(
        self,
        task: Task,
        candidate_id: str | None,
        candidate_hash: str | None,
        code: str,
        message: str,
        *,
        status_code: int = 409,
        expected_hash: str | None = None,
        actual_hash: str | None = None,
        expected_version: str | None = None,
        actual_version: str | None = None,
    ) -> Never:
        error = PlanConfirmationGuardError(
            code,
            message,
            status_code,
            expected_hash=expected_hash,
            actual_hash=actual_hash,
            expected_version=expected_version,
            actual_version=actual_version,
        )
        self._record_confirmation_rejection(
            task,
            candidate_id,
            candidate_hash,
            error,
            expected_version=expected_version,
            actual_version=actual_version,
        )
        raise error

    def _record_confirmation_rejection(
        self,
        task: Task,
        candidate_id: str | None,
        candidate_hash: str | None,
        error: PlanConfirmationGuardError,
        *,
        expected_version: str | None = None,
        actual_version: str | None = None,
    ) -> None:
        try:
            planning = self._store.get_current_parameter_planning(task.task_id)
        except ParameterPlanningGuardError:
            planning = task.parameter_planning_result
        event = create_audit_event(
            task_id=task.task_id,
            actor_id=task.actor.actor_id,
            actor_role=task.actor.actor_role,
            display_name=task.actor.display_name,
            occurred_at=self._clock.now(),
            result="REJECTED",
            rule_set_version=task.versions.rule_set_version,
            candidate_id=candidate_id,
            candidate_hash=candidate_hash,
            planning_result_id=(
                None if planning is None else planning.planning_result_id
            ),
            planning_result_version=(
                None if planning is None else planning.planning_result_version
            ),
            rejection_code=error.code,
            expected_hash=error.expected_hash,
            actual_hash=error.actual_hash,
            expected_version=expected_version or error.expected_version,
            actual_version=actual_version or error.actual_version,
        )
        self._store.append_audit_event(event)

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
        except (
            ParameterPlanningAssetError,
            ParameterPlanningGuardError,
            CaseRetrievalAssetError,
        ) as error:
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
