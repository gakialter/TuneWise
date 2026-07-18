from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .assets import AssetIntegrityError, PublicAssetLoader
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
from .store import (
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
    ) -> None:
        self._asset_loader = asset_loader
        self._store = store
        self._id_generator = id_generator or DemoTaskIdGenerator()
        self._demo_asset_root = demo_asset_root
        self._expected_dataset_manifest_hash = expected_dataset_manifest_hash
        self._clock = clock or SystemClock()

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
