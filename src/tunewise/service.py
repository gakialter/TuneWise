from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .assets import AssetIntegrityError, PublicAssetLoader
from .case_retrieval import (
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
)
from .store import (
    CaseRetrievalResultConflictError,
    DiagnosticResultConflictError,
    DetectionResultConflictError,
    ImportSnapshotConflictError,
    StoredDetectionInput,
    TaskStore,
)


@dataclass(frozen=True, slots=True)
class DemoTaskIdGenerator:
    def new_id(self) -> str:
        return "tw-demo-task-001"


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
            ) from error

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
            ) from error

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
